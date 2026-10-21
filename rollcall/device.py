"""The only module that talks to a K40. Everything goes through pyzk; the protocol is not reimplemented.

Rules this module exists to enforce:

* ``enable_device()`` runs in a ``finally`` every time, and ``disconnect()`` runs even if enabling
  fails. A device left disabled freezes in front of a lecture hall.
* One conversation per device at a time. A pull and an enrollment must never overlap.
* uid (the device's internal slot) is set equal to user_id. Verified on the real K40 for 2001, 5999
  and 9001, and it removes a lookup from every write and delete.
* Finger status is read with ``get_templates()`` in bulk. ``get_user_template()`` returned None for
  an 872 byte template that the bulk read listed (verified on device 2026-09-15).
* Enrollment runs with the device enabled, because the device must be in capture mode.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Iterator

ADMIN = 14
NORMAL = 0

# What the terminal was asked and what it answered, in the log file, because a terminal that goes
# quiet on somebody else's machine leaves nothing else behind. A capture that waited sixty seconds
# and timed out wrote not one line on 2026-09-22, so the fault had to be reconstructed from the
# register afterwards. Nothing here logs a name or a keypad password: user ids and counts only.
log = logging.getLogger("rollcall.device")


class DeviceError(Exception):
    """A failure with a plain-English message for the lecturer and a hint for the admin."""

    def __init__(self, message: str, hint: str = "", code: str = "device_error"):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.code = code


class DeviceBusy(DeviceError):
    def __init__(self) -> None:
        super().__init__(
            "The device is busy with another task.",
            "Wait for the current pull or enrolment to finish, then try again.",
            "device_busy",
        )


@dataclass(frozen=True)
class DeviceTarget:
    ip: str
    port: int = 4370
    comm_key: int = 0
    timeout: int = 10


@dataclass
class DeviceSnapshot:
    serial: str
    firmware: str
    platform: str
    device_name: str
    device_time: datetime
    pc_time: datetime
    users: int
    user_capacity: int
    templates: int
    template_capacity: int
    records: int
    record_capacity: int

    @property
    def clock_drift_seconds(self) -> int:
        return int((self.device_time - self.pc_time).total_seconds())


@dataclass
class DeviceUser:
    user_id: str
    uid: int
    name: str
    privilege: int
    has_password: bool


@dataclass
class RawPunch:
    user_id: str
    timestamp: datetime
    verify_type: int | None
    punch_state: int | None


@dataclass
class TemplateInfo:
    user_id: int
    finger_index: int
    size: int


@dataclass
class EnrollResult:
    outcome: str                      # captured | not_captured | timeout | error
    detail: str = ""
    fingers_after: list[int] = field(default_factory=list)


def _default_factory(target: DeviceTarget):
    """The library that talks to the terminal: pyzk, or pyzatt when ROLLCALL_DEVICE_BACKEND says so.

    Both are imported lazily so tests and the diagnostics page work without either installed. The
    choice exists because pyzk is GPL-2.0 and pyzatt is MIT; the protocol work is identical.
    """
    from . import zatt_backend

    if zatt_backend.chosen() == "pyzatt":
        return zatt_backend.factory(target)

    from zk import ZK

    return ZK(target.ip, port=target.port, timeout=target.timeout, password=target.comm_key,
              force_udp=False, ommit_ping=True)


_locks: dict[tuple[str, int], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(target: DeviceTarget) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((target.ip, target.port), threading.Lock())


class K40:
    def __init__(self, target: DeviceTarget, zk_factory: Callable = _default_factory,
                 port_open: Callable[[], bool] | None = None):
        self.target = target
        self._factory = zk_factory
        # Asked before the heartbeat hands the terminal to pyzk (see ping). A fake terminal has no
        # port to knock on, so only the real one is knocked unless a test passes its own answer.
        self._port_open = port_open or (self._knock if zk_factory is _default_factory else (lambda: True))
        # The live connection while a capture is running, so it can be stopped from another thread.
        self._capturing = None
        self._cancelled = threading.Event()

    # -- connection discipline -------------------------------------------------------------

    def _knock(self) -> bool:
        from .diagnostics import tcp_open

        return tcp_open(self.target.ip, self.target.port, timeout=2.0)

    def _unreachable(self) -> DeviceError:
        return DeviceError(
            f"Could not connect to the device at {self.target.ip}:{self.target.port}.",
            "Check the cable, that the PC is on 192.168.1.100 with the gateway blank, and the "
            "device IP under Menu > COMM. > Ethernet. Run the connection check for details.",
            "unreachable",
        )

    @contextmanager
    def session(self, disable: bool = True, wait_seconds: float = 5, knock: bool = False) -> Iterator[object]:
        lock = _lock_for(self.target)
        if not lock.acquire(timeout=wait_seconds):
            raise DeviceBusy()
        conn = None
        try:
            if knock and not self._port_open():
                raise self._unreachable()
            try:
                conn = self._factory(self.target).connect()
            except Exception as exc:  # pyzk raises a range of types for the same fault
                raise self._unreachable() from exc
            if disable:
                conn.disable_device()
            yield conn
        finally:
            try:
                if conn is not None:
                    try:
                        conn.enable_device()
                    finally:
                        conn.disconnect()
            except Exception:
                # Nothing more can be done from here; the next connect re-enables the device.
                pass
            finally:
                lock.release()

    # -- reads -----------------------------------------------------------------------------

    def snapshot(self) -> DeviceSnapshot:
        with self.session() as conn:
            conn.read_sizes()
            device_time = conn.get_time()
            pc_time = datetime.now()
            return DeviceSnapshot(
                serial=_text(conn.get_serialnumber()),
                firmware=_text(conn.get_firmware_version()),
                platform=_text(conn.get_platform()),
                device_name=_text(conn.get_device_name()),
                device_time=device_time,
                pc_time=pc_time,
                users=conn.users,
                user_capacity=conn.users_cap,
                templates=conn.fingers,
                template_capacity=conn.fingers_cap,
                records=conn.records,
                record_capacity=conn.rec_cap,
            )

    def ping(self) -> str:
        """Is it there, and which one is it? The serial, read without disabling the terminal.

        `session()` disables the device by default, which is right for anything that writes and
        wrong for a heartbeat: a check every twenty seconds would take the terminal out of service
        for a moment each time, in front of a queue of students. This reads the serial and nothing
        else, and waits only briefly for the lock, because a heartbeat must never delay a pull.

        It knocks on the port first, for two seconds. pyzk's own connect spends ten seconds testing
        the port, ten opening the socket and ten waiting for a reply, so on an unplugged terminal a
        ping held the lock for thirty seconds against a twenty second heartbeat: the next ping found
        it held and said "busy", and the chip swapped between "not reachable" and "Something else is
        using the terminal" (2026-09-24). The restart does the same knock (see restart).
        """
        with self.session(disable=False, wait_seconds=0.5, knock=True) as conn:
            return _text(conn.get_serialnumber())

    def read_serial(self) -> str:
        with self.session() as conn:
            return _text(conn.get_serialnumber())

    def read_users(self) -> list[DeviceUser]:
        with self.session() as conn:
            return [DeviceUser(str(u.user_id), int(u.uid), u.name, int(u.privilege), bool(u.password))
                    for u in conn.get_users()]

    def read_templates(self) -> list[TemplateInfo]:
        with self.session() as conn:
            return _templates(conn)

    def record_count(self) -> int:
        """How many scans the terminal holds, without taking it out of service.

        What a class taken live asks every few seconds, so it reads the scans themselves only when
        this number has moved. Disabling the terminal for it would lock out the student at the
        reader at that moment, every few seconds, for the length of the queue.
        """
        with self.session(disable=False, wait_seconds=1) as conn:
            conn.read_sizes()
            return int(conn.records)

    def read_attendance(self, disable: bool = True) -> tuple[str, list[RawPunch]]:
        """Return the serial alongside the records so a pull can refuse the wrong device.

        ``disable=False`` for a class taken live, where students are scanning while it reads. A scan
        made during the read and missed by it is not lost either way: the count moves, and the
        read the class makes when it ends takes everything. Whether the terminal ever returns a
        half-written record to a read made while a student scans is unverified on the K40.
        """
        with self.session(disable=disable) as conn:
            serial = _text(conn.get_serialnumber())
            records = [RawPunch(str(r.user_id), r.timestamp, _int_or_none(r.status), _int_or_none(r.punch))
                       for r in conn.get_attendance()]
            return serial, records

    # -- writes ----------------------------------------------------------------------------

    def push_users(self, users: list[dict], on_each: Callable[[int], None] | None = None) -> int:
        """Create or update users. Each dict: user_id, name, privilege, password.

        ``on_each`` is given the running count after every one, so a screen can say "112 of 258"
        while a level goes onto the terminal rather than spinning for half a minute.
        """
        with self.session() as conn:
            for number, user in enumerate(users, start=1):
                _set_user(conn, user)
                if on_each is not None:
                    on_each(number)
            conn.refresh_data()
            log.info("pushed %d user(s) to the terminal: %s", len(users),
                     [u["user_id"] for u in users[:20]])
            return len(users)

    def delete_user(self, user_id: int) -> None:
        with self.session() as conn:
            conn.delete_user(uid=int(user_id))
            conn.refresh_data()

    def remove_person(self, user_id: int) -> bool:
        """Take one person and their fingerprints off the terminal, confirmed by reading back."""
        with self.session() as conn:
            conn.delete_user(uid=int(user_id))
            conn.refresh_data()
        still = any(int(u.user_id) == int(user_id) for u in self.read_users())
        if still:
            raise DeviceError(
                f"The terminal still has user {user_id}.",
                "Try again, and check the cable if it keeps happening.",
                "user_not_deleted",
            )
        return True

    def empty_people(self, on_start: Callable[[int], None] | None = None,
                     on_each: Callable[[int], None] | None = None) -> dict:
        """Take every person and every fingerprint off the terminal, one user at a time.

        pyzk can wipe everything in one command, but that takes the scans with it, and scans are
        the one thing on this terminal that cannot be recreated. Deleting user by user leaves the
        attendance log alone, and the count read back afterwards is what is reported.
        """
        with self.session() as conn:
            users = list(conn.get_users())
            # How many there are is only known once they have been read, which is why the count
            # arrives here rather than before the call.
            if on_start is not None:
                on_start(len(users))
            for number, user in enumerate(users, start=1):
                conn.delete_user(uid=int(user.uid))
                if on_each is not None:
                    on_each(number)
            conn.refresh_data()
        left = self.read_users()
        log.info("emptied the terminal: %d removed, %d left", len(users) - len(left), len(left))
        return {"removed": len(users) - len(left), "left": len(left)}

    def remove_block(self, first_id: int, last_id: int,
                     on_start: Callable[[int], None] | None = None,
                     on_each: Callable[[int], None] | None = None) -> int:
        """Take every user whose ID is in a level's block off the terminal, with their fingers.

        For clearing a level's roster. What the terminal holds is read rather than what the register
        believes is on it, so a student sent from an earlier setup, or whose on_device flag went
        stale, goes too. Confirmed by reading back; the scan log is left alone, as empty_people does.
        """
        def in_block(user) -> bool:
            text = str(user.user_id).strip()
            return text.isdigit() and first_id <= int(text) <= last_id

        with self.session() as conn:
            users = [u for u in conn.get_users() if in_block(u)]
            if on_start is not None:
                on_start(len(users))
            for number, user in enumerate(users, start=1):
                conn.delete_user(uid=int(user.uid))
                if on_each is not None:
                    on_each(number)
            conn.refresh_data()
        left = [u.user_id for u in self.read_users() if in_block(u)]
        log.info("removed IDs %d to %d from the terminal: %d removed, %d left",
                 first_id, last_id, len(users) - len(left), len(left))
        if left:
            raise DeviceError(
                f"The terminal still has {len(left)} of these students, such as {left[0]}.",
                "Nothing was deleted from the register. Try again, and check the cable if it keeps "
                "happening.",
                "user_not_deleted",
            )
        return len(users)

    def delete_finger(self, user_id: int, finger_index: int) -> list[int]:
        """Take one finger off the terminal and return the fingers that are still on it.

        Confirmed by reading the templates back, the same discipline as enrolling: the device's own
        answer is not evidence that the template is gone.
        """
        if not 0 <= finger_index <= 9:
            raise ValueError("finger_index must be 0 to 9")
        with self.session() as conn:
            # By uid alone, never with user_id. Given a user_id over TCP, pyzk packs a str where
            # struct needs bytes (zk/base.py, delete_user_template, `pack('<24sB', str(user_id),
            # ...)`), so every call raised struct.error and Remove could never have worked on a
            # real terminal. uid equals user_id on every write, so the uid path reaches the same
            # template: verified on the K40 on 2026-09-22, finger 6 of user 2001 deleted.
            conn.delete_user_template(uid=int(user_id), temp_id=int(finger_index))
            conn.refresh_data()
        left = sorted(t.finger_index for t in self.read_templates() if t.user_id == int(user_id))
        if finger_index in left:
            raise DeviceError(
                f"The terminal still has finger {finger_index} for user {user_id}.",
                "Try again, and check the cable if it keeps happening.",
                "template_not_deleted",
            )
        return left

    def demote_all_admins(self, before: Callable[[str], None] | None = None) -> list[str]:
        """Lockout recovery: make every Super Admin a normal user over TCP.

        Works without an admin fingerprint or password because TCP ignores keypad roles
        (verified on device 2026-09-15). That is also why the Comm Key matters.

        `before` receives the serial on the same connection, before anything is written, and
        raises to stop, so the wrong terminal is never touched.
        """
        demoted = []
        with self.session() as conn:
            if before is not None:
                before(_text(conn.get_serialnumber()))
            for u in conn.get_users():
                if int(u.privilege) & 0xE == ADMIN:
                    conn.set_user(uid=u.uid, name=u.name, privilege=NORMAL, password=u.password,
                                  group_id=u.group_id, user_id=u.user_id, card=u.card)
                    demoted.append(str(u.user_id))
            conn.refresh_data()
        return demoted

    def clear_attendance_if_count(self, expected_records: int) -> bool:
        """Clear only if the device still holds exactly the records the caller has stored.

        The device is disabled for the whole check-and-clear, so no scan can land in between.
        """
        with self.session() as conn:
            conn.read_sizes()
            if conn.records != expected_records:
                return False
            conn.clear_attendance()
            conn.refresh_data()
            return True

    def set_time(self, when: datetime | None = None) -> datetime:
        """Set the terminal's clock and return what it reads afterwards.

        "Now" is taken inside the session, at the moment of writing. It used to be taken before
        waiting for the terminal, so the wait was written into the clock: on 2026-09-23 the owner's
        K40 was set 9 and 10 seconds slow on three starts running, every scan was stamped that much
        early, and the first scan after Start landed before the class had opened. The clock is read
        back and set once more if it is still more than two seconds out.
        """
        with self.session() as conn:
            for attempt in range(2):
                conn.set_time(when or datetime.now().replace(microsecond=0))
                reads = conn.get_time()
                drift = (reads - datetime.now()).total_seconds()
                if when is not None or abs(drift) <= 2:
                    break
                log.info("clock set but reads %+.0fs from this PC; setting it again", drift)
            return reads

    def restart(self, back_within: float = 120, settle: float = 10, every: float = 3,
                on_wait: Callable[[float], None] | None = None,
                port_open: Callable[[], bool] | None = None) -> float:
        """Restart the terminal and wait until it answers again. Returns the seconds it took.

        The one cure proven for a terminal that answers the enrol command with OK and then never
        asks for a finger: on 2026-09-22 this K40 ignored every capture for over an hour, whatever
        form the command took, and after a restart from here it asked twice in a row. It came back
        in 35 seconds still holding its user. Everything on a terminal lives in its flash, so a
        restart is not a reset.

        The device lock is held throughout, so nothing else in this program tries the terminal
        while it is away: the heartbeat answers "busy" for those seconds rather than "gone".
        """
        lock = _lock_for(self.target)
        if not lock.acquire(timeout=5):
            raise DeviceBusy()
        try:
            try:
                conn = self._factory(self.target).connect()
            except Exception as exc:
                raise DeviceError(
                    f"Could not connect to the device at {self.target.ip}:{self.target.port}.",
                    "A terminal that cannot be reached cannot be restarted from here. Switch it "
                    "off and on at the wall, then run the connection check.",
                    "unreachable",
                ) from exc
            try:
                conn.restart()
            finally:
                # pyzk's restart leaves its socket open to a terminal that is already going away.
                sock = getattr(conn, "_ZK__sock", None)
                if sock is not None:
                    _quietly(sock.close)
            log.info("restart sent to the terminal")
            started = time.monotonic()

            def report() -> float:
                gone = time.monotonic() - started
                if on_wait is not None:
                    on_wait(gone)
                return gone

            # Counted a second at a time, so the bar moves while the terminal is dark. It sat at
            # "0 of 45" for the whole of a real restart when it moved only on a failed reconnect
            # (2026-09-22), which looks exactly like a program that has hung.
            while time.monotonic() - started < settle:
                report()
                time.sleep(min(1.0, settle))
            # Knock on the port before asking pyzk. pyzk's connect tests the port with a timeout of
            # its own fixed at ten seconds (zk/base.py, test_tcp, settimeout(10)), so on a terminal
            # still starting up each attempt blocked for ten seconds and the bar stood still at
            # "10 of 45" (2026-09-22). Two seconds is ample on a direct cable.
            if port_open is None:
                from .diagnostics import tcp_open

                def port_open() -> bool:
                    return tcp_open(self.target.ip, self.target.port, timeout=2.0)
            knock = replace(self.target, timeout=3)
            while True:
                gone = report()
                if not port_open():
                    if gone >= back_within:
                        raise _not_back(back_within)
                    time.sleep(every)
                    continue
                try:
                    answer = self._factory(knock).connect()
                    answer.get_serialnumber()
                    _quietly(answer.disconnect)
                    log.info("terminal back after %.0fs", gone)
                    return gone
                except Exception:
                    if gone >= back_within:
                        raise _not_back(back_within)
                    time.sleep(every)
        finally:
            lock.release()

    # -- enrollment ------------------------------------------------------------------------

    def stop_capture(self) -> bool:
        """Stop a capture this K40 object started, from another thread.

        The enrolling thread is blocked inside pyzk waiting for the student to press, and the
        per-device lock means no second connection can be opened to tell the terminal to stop. So
        the live connection is kept while a capture runs, and cancelling uses that: the terminal is
        told to cancel, and then the socket is shut down so the blocked read returns at once rather
        than sitting there for the rest of the minute. Asked for after a first enrolment: a capture
        started for the wrong student had no way back (2026-09-21).
        """
        conn = self._capturing
        if conn is None:
            return False
        self._cancelled.set()
        _quietly(conn.cancel_capture)
        sock = getattr(conn, "_ZK__sock", None) or getattr(conn, "_sock", None)
        if sock is not None:
            # Shutdown alone does not wake a recv already blocked on Windows: measured against the
            # real K40 on 2026-09-22, where stopping still took the full 60 second enrolment
            # timeout. Closing the socket does wake it, and the session's own clean-up is written
            # to survive a connection that has gone (2026-09-21).
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        return True

    def enroll_finger(self, user_id: int, finger_index: int) -> EnrollResult:
        """Put the device into capture mode for one finger and wait for three presses.

        pyzk's enroll_user waits up to 60 seconds for each device event. If the student never
        presses, a socket timeout escapes before pyzk cancels capture, so that is done here.
        The result is confirmed by reading templates back rather than trusting the return value.
        """
        if not 0 <= finger_index <= 9:
            raise ValueError("finger_index must be 0 to 9")
        outcome, detail = "error", ""
        started = time.monotonic()
        log.info("capture asked for: user %s, finger %s", user_id, finger_index)
        self._cancelled.clear()
        with self.session(disable=False) as conn:
            self._capturing = conn
            try:
                ok = conn.enroll_user(uid=int(user_id), temp_id=int(finger_index), user_id=str(user_id))
                outcome = "captured" if ok else "not_captured"
                if not ok:
                    detail = "The device did not save the finger. It may be a poor scan, or already enrolled."
            except socket.timeout:
                outcome, detail = "timeout", "No finger was pressed in time."
                _quietly(conn.cancel_capture)
            except Exception as exc:
                outcome, detail = "error", f"{type(exc).__name__}: {exc}"
                _quietly(conn.cancel_capture)
            finally:
                self._capturing = None
            if self._cancelled.is_set():
                outcome, detail = "cancelled", "The capture was stopped before a finger was saved."

        fingers = sorted(t.finger_index for t in self.read_templates() if t.user_id == int(user_id))
        if finger_index in fingers and outcome != "captured":
            # The usual case on this K40, not a rescue. pyzk counts a press only at a quality score
            # of exactly 100 and this terminal sends 49 to 73, so enroll_user returns False for a
            # finger the terminal has just stored (seen on every capture on 2026-09-22). The
            # template read back is the evidence; what pyzk said goes to the log, not the screen,
            # where "Device reported not_captured" sat inside a success message.
            log.info("pyzk reported %s for user %s finger %s, but the template is on the "
                     "terminal", outcome, user_id, finger_index)
            outcome, detail = "captured", ""
        elif finger_index not in fingers and outcome == "captured":
            outcome, detail = "not_captured", "Device reported success but no template was found."
        log.info("capture ended %s after %.0fs: user %s, finger %s, fingers on the terminal now %s%s",
                 outcome, time.monotonic() - started, user_id, finger_index, fingers,
                 f" ({detail})" if detail else "")
        return EnrollResult(outcome, detail, fingers)


def _not_back(back_within: float) -> DeviceError:
    return DeviceError(
        f"The terminal has not come back {int(back_within)} seconds after the restart.",
        "Look at its screen. If it is still starting, wait and run the connection check; if it is "
        "dark, check its power.",
        "not_back",
    )


def _set_user(conn, user: dict) -> None:
    user_id = int(user["user_id"])
    privilege = int(user.get("privilege") or NORMAL)
    password = user.get("password") or ""
    if privilege == ADMIN and not password:
        # An admin with no password is locked out of the menu by one cut finger.
        raise DeviceError(
            f"Refusing to push user {user_id} as Super Admin without a keypad password.",
            "Set a 1 to 8 digit password for this person first.",
            "admin_needs_password",
        )
    conn.set_user(uid=user_id, name=str(user["name"]), privilege=privilege, password=str(password),
                  group_id="", user_id=str(user_id), card=0)


def _templates(conn) -> list[TemplateInfo]:
    return [TemplateInfo(int(t.uid), int(t.fid), int(t.size)) for t in conn.get_templates()]


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip().strip("\x00")


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _quietly(fn) -> None:
    try:
        fn()
    except Exception:
        pass
