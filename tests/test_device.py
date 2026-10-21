import threading
import time
from datetime import datetime, timedelta

import pytest

from fake_zk import FakeRecord, FakeUser
from rollcall import services
from rollcall.device import ADMIN, DeviceBusy, DeviceError, DeviceTarget, K40

TARGET = DeviceTarget("192.168.1.201")


def make(fake):
    return K40(TARGET, zk_factory=fake.factory())


def test_the_heartbeat_gives_up_at_once_on_a_terminal_whose_port_is_shut(fake):
    """pyzk spends thirty seconds finding an unplugged terminal (ten testing the port, ten opening
    the socket, ten waiting for a reply) and the ping held the lock throughout, against a twenty
    second heartbeat. The next ping found it held and said "busy", and the chip swapped between
    "not reachable" and "Something else is using the terminal" (2026-09-24)."""
    shut = K40(TARGET, zk_factory=fake.factory(), port_open=lambda: False)
    started = time.monotonic()
    with pytest.raises(DeviceError) as raised:
        shut.ping()
    assert time.monotonic() - started < 1
    assert raised.value.code == "unreachable"
    assert raised.value.message == "Could not connect to the device at 192.168.1.201:4370."
    assert fake.connections == 0                   # never handed to pyzk
    assert make(fake).ping() == "FDDW250226081"    # and the lock is free again at once


def test_only_the_heartbeat_knocks(fake):
    """A pull or a push keeps the connect it always had; the knock is for the check that runs
    every twenty seconds whether or not anybody is using the terminal."""
    shut = K40(TARGET, zk_factory=fake.factory(), port_open=lambda: False)
    assert shut.read_serial() == "FDDW250226081"


def test_a_fake_terminal_is_never_knocked(fake):
    """The tests and the dev server's fake terminal have no port, so the knock is for the real one."""
    started = time.monotonic()
    assert make(fake).ping() == "FDDW250226081"
    assert time.monotonic() - started < 1


def test_the_ping_says_where_it_could_not_connect(conn, fake):
    """The banner builds its sentence from this, so it ends in exactly one full stop."""
    seen = services.ping(conn, 1, lambda target: K40(target, zk_factory=fake.factory(), port_open=lambda: False))
    assert seen["state"] == "unreachable"
    assert seen["detail"] == "Could not connect to the device at 192.168.1.201:4370."


def test_device_is_enabled_and_disconnected_when_the_work_fails(fake):
    k40 = make(fake)
    with pytest.raises(RuntimeError):
        with k40.session() as conn:
            conn.get_users()
            raise RuntimeError("app crashed mid-read")
    assert fake.enabled is True
    assert fake.calls[-2:] == ["enable_device", "disconnect"]
    assert fake.open_connections == 0


def test_disconnect_still_runs_when_enable_fails(fake):
    fake.fail.add("enable_device")
    with make(fake).session() as conn:
        conn.get_users()
    assert fake.calls[-1] == "disconnect"
    assert fake.open_connections == 0


def test_unreachable_device_gives_a_named_error(fake):
    fake.reachable = False
    with pytest.raises(DeviceError) as err:
        make(fake).snapshot()
    assert err.value.code == "unreachable"
    assert "192.168.1.100" in err.value.hint


def test_one_conversation_per_device(fake):
    k40 = make(fake)
    entered, release = threading.Event(), threading.Event()

    def hold():
        with k40.session():
            entered.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    entered.wait(5)
    try:
        with pytest.raises(DeviceBusy):
            with k40.session(wait_seconds=0.1):
                pass
    finally:
        release.set()
        t.join()


def test_uid_equals_user_id_on_push(fake):
    make(fake).push_users([{"user_id": 2001, "name": "EFIKOSLI Opazsitofo E.", "privilege": 0, "password": ""}])
    assert fake.users[2001].user_id == "2001"


def test_admin_without_password_is_refused(fake):
    with pytest.raises(DeviceError) as err:
        make(fake).push_users([{"user_id": 1, "name": "LECTURER", "privilege": ADMIN, "password": ""}])
    assert err.value.code == "admin_needs_password"
    assert fake.users == {}
    assert fake.enabled is True


def test_demote_all_admins(fake):
    fake.users = {1: FakeUser(1, "1", "LECTURER", ADMIN, "4321"), 2001: FakeUser(2001, "2001", "STUDENT")}
    assert make(fake).demote_all_admins() == ["1"]
    assert fake.users[1].privilege == 0
    assert fake.users[1].password == "4321"


def test_enroll_captured_is_confirmed_by_reading_templates(fake):
    fake.users = {2001: FakeUser(2001, "2001", "STUDENT")}
    result = make(fake).enroll_finger(2001, 0)
    assert result.outcome == "captured"
    assert result.fingers_after == [0]
    assert "disable_device" not in fake.calls[: fake.calls.index("enroll_user")]


def test_a_capture_pyzk_calls_failed_but_the_terminal_stored_says_only_captured(fake):
    """Every real capture on the K40 on 2026-09-22 came back from pyzk as False while the terminal
    held the finger. The template read back decides, and the screen says captured and nothing
    else: "Device reported not_captured" had been sitting inside a success message."""
    fake.users = {2001: FakeUser(2001, "2001", "STUDENT")}
    fake.enroll_mode = "stored_but_false"
    result = make(fake).enroll_finger(2001, 6)
    assert result.outcome == "captured"
    assert result.fingers_after == [6]
    assert result.detail == ""


def test_enroll_timeout_cancels_capture_and_leaves_device_enabled(fake):
    fake.users = {2001: FakeUser(2001, "2001", "STUDENT")}
    fake.enroll_mode = "timeout"
    result = make(fake).enroll_finger(2001, 1)
    assert result.outcome == "timeout"
    assert "cancel_capture" in fake.calls
    assert fake.enabled is True
    assert fake.open_connections == 0


def test_enroll_refused_reports_not_captured(fake):
    fake.enroll_mode = "refuse"
    assert make(fake).enroll_finger(2001, 0).outcome == "not_captured"


def test_clear_refuses_if_device_count_changed(fake):
    fake.records = [FakeRecord("2001", datetime(2026, 9, 15, 9, 0))]
    assert make(fake).clear_attendance_if_count(2) is False
    assert len(fake.records) == 1
    assert make(fake).clear_attendance_if_count(1) is True
    assert fake.records == []


def test_snapshot_reports_clock_drift(fake):
    fake.clock_offset = timedelta(minutes=5)
    snap = make(fake).snapshot()
    assert 290 <= snap.clock_drift_seconds <= 310


def test_a_capture_started_by_mistake_can_be_stopped(tmp_path, conn, fake, k40_factory):
    """Asked for after a first enrolment: a capture started for the wrong student held the terminal
    for the rest of the minute, and the register with it, with no way back (2026-09-21)."""
    from rollcall import db, enrollment

    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " device_name, active, on_device, consent_recorded_at, created_at)"
                 " VALUES ('student', 2001, 1, 'Z/1', 'SANI', 'Halima', 'SANI Halima', 1, 1, ?, ?)",
                 (db.now(), db.now()))
    conn.commit()
    person_id = conn.execute("SELECT id FROM people").fetchone()["id"]

    fake.enroll_mode = "wait"
    manager = enrollment.EnrollmentManager(tmp_path / "test.db", factory=k40_factory)
    manager.start(conn, person_id, enrollment.TWO_FINGERS[0], 1, consent_confirmed=True)
    assert fake.capture_started.wait(5), "the fake terminal never started capturing"
    assert manager.status()["state"] == "waiting_for_finger"

    stopped = manager.cancel()
    assert stopped["state"] == "finished"
    assert stopped["outcome"] == "cancelled", stopped
    assert "stopped" in stopped["detail"].lower()
    # Nothing was written for a capture that never took a finger.
    assert not conn.execute("SELECT 1 FROM fingers WHERE person_id = ?", (person_id,)).fetchone()
    # And the terminal was told, rather than the app simply forgetting about it.
    assert "cancel_capture" in fake.calls

    with pytest.raises(enrollment.EnrollmentError, match="No capture is waiting"):
        manager.cancel()


def test_a_capture_pushes_the_student_even_when_the_register_thinks_they_are_there(
        tmp_path, conn, fake, k40_factory):
    """Reported on a second run: after the terminal was emptied, Enrol said it was waiting for a
    finger and the terminal showed nothing.

    Emptying a terminal from its own menu leaves every on_device flag saying 1 while the terminal
    holds nobody, and a capture for a user that is not on it waits for a finger that can never
    come. Reproduced on the real K40 on 2026-09-22: the state reached waiting_for_finger and the
    terminal never prompted. So the student is pushed before every capture, whatever the register
    believes.
    """
    from rollcall import db, enrollment

    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " device_name, active, on_device, consent_recorded_at, created_at)"
                 " VALUES ('student', 2001, 1, 'Z/1', 'SANI', 'Halima', 'SANI Halima', 1, 1, ?, ?)",
                 (db.now(), db.now()))
    conn.commit()
    person_id = conn.execute("SELECT id FROM people").fetchone()["id"]
    assert fake.users == {}, "the terminal starts empty, as it does after being emptied"

    fake.enroll_mode = "wait"
    manager = enrollment.EnrollmentManager(tmp_path / "test.db", factory=k40_factory)
    manager.start(conn, person_id, enrollment.TWO_FINGERS[0], 1, consent_confirmed=True)
    assert fake.capture_started.wait(5), "the fake terminal never started capturing"

    # The point: they are on the terminal now, so the capture is one it can actually answer.
    assert 2001 in fake.users, "the student was not pushed before the capture"
    manager.cancel()


def test_a_waiting_capture_says_when_its_wait_began(tmp_path, conn, fake, k40_factory):
    """The screen counts down from this, so it has to start when the terminal was asked.

    A lecturer watched "Waiting for the finger" for a full minute with nothing to say how long it
    would last and no way to tell a terminal that was waiting from one that had ignored the
    command (2026-09-22). The push runs first and takes most of a minute for a whole level, so a
    countdown from ``started_at`` would already have spent its time before the terminal was asked
    for anything.
    """
    from rollcall import db, enrollment

    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " device_name, active, on_device, consent_recorded_at, created_at)"
                 " VALUES ('student', 2001, 1, 'Z/1', 'SANI', 'Halima', 'SANI Halima', 1, 1, ?, ?)",
                 (db.now(), db.now()))
    conn.commit()
    person_id = conn.execute("SELECT id FROM people").fetchone()["id"]

    fake.enroll_mode = "wait"
    manager = enrollment.EnrollmentManager(tmp_path / "test.db", factory=k40_factory)
    manager.start(conn, person_id, enrollment.TWO_FINGERS[0], 1, consent_confirmed=True)
    assert fake.capture_started.wait(5), "the fake terminal never started capturing"

    waiting = manager.status()
    assert waiting["state"] == "waiting_for_finger"
    assert waiting["waits_for_seconds"] == enrollment.CAPTURE_SECONDS
    began = datetime.fromisoformat(waiting["waiting_since"])
    assert began >= datetime.fromisoformat(waiting["started_at"]), "the wait began before the push"
    assert (datetime.now() - began).total_seconds() < 30
    manager.cancel()


def test_one_finger_can_be_taken_off_the_terminal(conn, fake, k40_factory):
    """Remove, on the enrolment screen, had never once run: the fake had no delete_user_template
    and the real pyzk raises struct.error when handed a user_id over TCP (2026-09-22)."""
    from fake_zk import FakeFinger
    from rollcall import db, enrollment

    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " device_name, active, on_device, created_at)"
                 " VALUES ('student', 2001, 1, 'Z/1', 'SANI', 'Halima', 'SANI Halima', 1, 1, ?)",
                 (db.now(),))
    person_id = conn.execute("SELECT id FROM people").fetchone()["id"]
    fake.users[2001] = FakeUser(2001, "2001", "SANI Halima")
    for finger in (6, 7):
        fake.templates[(2001, finger)] = FakeFinger(2001, finger)
        conn.execute("INSERT INTO fingers(person_id, finger_index, first_seen_at, last_seen_at)"
                     " VALUES (?, ?, ?, ?)", (person_id, finger, db.now(), db.now()))
    conn.commit()

    left = enrollment.remove_finger(conn, person_id, 6, 1, factory=k40_factory)

    assert left["fingers"] == [7]
    assert (2001, 6) not in fake.templates, "the terminal still has the finger"
    assert (2001, 7) in fake.templates, "the other finger went with it"
    kept = [r["finger_index"] for r in conn.execute(
        "SELECT finger_index FROM fingers WHERE person_id = ?", (person_id,))]
    assert kept == [7]


def test_one_person_can_be_taken_off_the_terminal(conn, fake, k40_factory):
    """Asked for after a first enrolment: somebody sent to the terminal by mistake, or who has
    left, had no way off it short of emptying the whole thing (2026-09-21)."""
    from rollcall import db, services

    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " device_name, active, on_device, created_at)"
                 " VALUES ('student', 2001, 1, 'Z/1', 'SANI', 'Halima', 'SANI Halima', 1, 1, ?)",
                 (db.now(),))
    person_id = conn.execute("SELECT id FROM people").fetchone()["id"]
    conn.execute("INSERT INTO fingers(person_id, finger_index, first_seen_at, last_seen_at)"
                 " VALUES (?, 6, ?, ?)", (person_id, db.now(), db.now()))
    conn.commit()
    fake.users[2001] = FakeUser(uid=2001, user_id="2001", name="SANI Halima")

    done = services.remove_from_device(conn, 1, person_id, 1, factory=k40_factory)

    assert done["on_device"] is False
    assert 2001 not in fake.users
    row = conn.execute("SELECT on_device FROM people WHERE id = ?", (person_id,)).fetchone()
    assert row["on_device"] == 0
    # The fingerprints named templates that are gone with the user.
    assert not conn.execute("SELECT 1 FROM fingers WHERE person_id = ?", (person_id,)).fetchone()
    said = conn.execute("SELECT detail FROM audit_log WHERE action = 'device.remove_person'").fetchone()
    assert "SANI Halima" in said["detail"]


def test_emptying_the_terminal_needs_its_serial_and_leaves_the_scans(conn, fake, k40_factory):
    from rollcall import db, services

    for n in (2001, 2002):
        conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname,"
                     " other_names, device_name, active, on_device, created_at)"
                     " VALUES ('student', ?, 1, ?, 'SANI', 'Halima', 'SANI Halima', 1, 1, ?)",
                     (n, f"Z/{n}", db.now()))
        fake.users[n] = FakeUser(uid=n, user_id=str(n), name="SANI Halima")
    conn.commit()
    person_id = conn.execute("SELECT id FROM people LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO fingers(person_id, finger_index, first_seen_at, last_seen_at)"
                 " VALUES (?, 6, ?, ?)", (person_id, db.now(), db.now()))
    conn.commit()
    fake.records = [FakeRecord("2001", datetime(2026, 9, 15, 9, 0, 0))]

    with pytest.raises(services.ServiceError, match="serial"):
        services.empty_device_people(conn, 1, 1, "not-the-serial", factory=k40_factory)
    assert fake.users, "nothing may be taken off the terminal before the serial is typed"

    done = services.empty_device_people(conn, 1, 1, fake.serial, factory=k40_factory)

    assert done == {"removed": 2, "left": 0}
    assert not fake.users
    # The scans on the terminal are the one thing that cannot be recreated, so they are left alone.
    assert len(fake.records) == 1
    assert not conn.execute("SELECT 1 FROM fingers").fetchone()
    assert not conn.execute("SELECT 1 FROM people WHERE on_device = 1").fetchone()


# -- restarting the terminal ---------------------------------------------------------------------
#
# The one cure proven for a terminal that answers the enrol command with OK and never asks for a
# finger: on 2026-09-22 the K40 did that for over an hour, and after a restart from the PC it asked
# twice in a row and came back in 35 seconds still holding its user.


def test_a_restart_waits_for_the_terminal_to_answer_again(fake):
    fake.restart_takes = 3
    k40 = make(fake)
    took = k40.restart(settle=0, every=0, port_open=lambda: True)

    assert fake.restarts == 1
    assert took >= 0
    assert fake.away_for == 0, "it returned before the terminal was back"
    # And the lock is free again: the next conversation is not told the device is busy.
    assert k40.read_serial() == fake.serial


def test_a_terminal_that_never_comes_back_is_said_plainly_and_frees_the_device(fake):
    fake.restart_takes = 10 ** 12   # never: a small number is used up in a few milliseconds
    k40 = make(fake)
    with pytest.raises(DeviceError) as raised:
        k40.restart(settle=0, every=0, port_open=lambda: True, back_within=0.05)
    assert raised.value.code == "not_back"
    assert "has not come back" in raised.value.message
    fake.away_for = 0
    assert k40.read_serial() == fake.serial, "the device lock was left held"


def test_restarting_from_the_register_reports_and_records_it(conn, fake, k40_factory):
    from rollcall import jobs, services

    done = services.restart_device(conn, 1, 1, factory=k40_factory, settle=0, every=0, port_open=lambda: True)

    assert fake.restarts == 1
    assert done["back_after_seconds"] >= 0
    assert jobs.current()["state"] == "finished"
    assert jobs.current()["outcome"] == "done"
    row = conn.execute("SELECT action, detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["action"] == "device.restart"
    assert "back after" in row["detail"]


def test_a_restart_reports_while_the_terminal_is_dark(fake):
    """The bar sat at "0 of 45" for a whole real restart, because it moved only when a reconnect
    failed, and looked exactly like a program that had hung (2026-09-22)."""
    fake.restart_takes = 0
    heard = []
    make(fake).restart(settle=0.05, every=0, port_open=lambda: True, on_wait=heard.append)
    assert heard, "nothing was reported while the terminal was away"
    assert heard == sorted(heard), "the count went backwards"
