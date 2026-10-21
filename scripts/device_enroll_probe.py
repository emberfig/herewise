"""Which form of the enrol command does this terminal obey, if any?

Run this when a capture says "waiting for the finger" and the terminal asks for nothing. Herewise
sends pyzk's CMD_STARTENROLL and waits sixty seconds; on a K40 running Ver 6.60 the terminal
answered OK and then sent not one byte (2026-09-22, three attempts in the register).

That OK is worth nothing. The same terminal answers OK to a command naming a user it has never
held, and to one asking for finger 99. Nor can the answer come over the wire as events: registered
for every event there is, this terminal sent nothing when a person at it pressed a finger and then
its keys (twice, 2026-09-22, with Herewise closed).

So the oracle is the one read that does work here: the fingerprints themselves. Each form asks for a
different finger number, and after its window the terminal's fingerprints are read back. A
fingerprint that appears names the form that made it. Anything it makes is deleted again at the end
unless --keep is given, because a real person's fingerprint under a test student should not stay.

    python scripts/device_enroll_probe.py 192.168.1.201 2001

Close Herewise first: it asks the terminal whether it is there every twenty seconds, and two
programs on one terminal is a fault of its own.
"""
from __future__ import annotations

import socket
import sys
import time
from struct import pack

from zk import ZK, const

WINDOW = 30                # seconds each form is given, enough for three presses
EVENTS = (const.EF_ATTLOG | const.EF_FINGER | const.EF_ENROLLUSER | const.EF_ENROLLFINGER
          | const.EF_VERIFY | const.EF_FPFTR | const.EF_BUTTON)


def connect(ip: str, port: int):
    return ZK(ip, port=port, timeout=10, password=0, force_udp=False, ommit_ping=True).connect()


def listen(conn, seconds: float, stop_on_first: bool = False) -> list[str]:
    """Every packet the terminal sends of its own accord, with the second it arrived."""
    sock = conn._ZK__sock
    sock.settimeout(1.0)
    started, heard = time.time(), []
    while time.time() - started < seconds:
        try:
            data = sock.recv(1032)
        except socket.timeout:
            continue
        except OSError as error:
            heard.append("the socket went: %s" % error)
            break
        heard.append("+%5.1fs  %3d bytes  %s" % (time.time() - started, len(data), data[:24].hex()))
        try:
            conn._ZK__ack_ok()
        except Exception:
            pass
        if stop_on_first:
            break
    return heard


def start_enroll(conn, user_id: str, finger: int, flag: int, shape: str):
    return conn._ZK__send_command(const.CMD_STARTENROLL,
                                  pack(shape, user_id.encode(), finger, flag))


def _close(conn) -> None:
    try:
        conn.cancel_capture()
    except Exception:
        pass
    try:
        conn.disconnect()
    except Exception:
        pass


def forms(user_id: str) -> list[tuple[str, int, object]]:
    """Each form asks for a different finger, so a fingerprint that appears names its form."""
    def pyzatt_way(c, finger):
        # pyzatt, written independently of pyzk, follows STARTENROLL with STARTVERIFY.
        start_enroll(c, user_id, finger, 1, "<24sbb")
        return c._ZK__send_command(const.CMD_STARTVERIFY)
    return [
        ("1  pyzk's form, finger 6 (what Herewise sends)", 6,
         lambda c: start_enroll(c, user_id, 6, 1, "<24sbb")),
        ("2  pyzk's form, finger 0 (what captured on 21 Sep)", 0,
         lambda c: start_enroll(c, user_id, 0, 1, "<24sbb")),
        ("3  pyzatt's order, finger 7", 7, lambda c: pyzatt_way(c, 7)),
        ("4  the SDK's 32 byte form, finger 8", 8,
         lambda c: start_enroll(c, user_id, 8, 1, "<24sII")),
        ("5  flag 0 rather than 1, finger 9", 9,
         lambda c: start_enroll(c, user_id, 9, 0, "<24sbb")),
    ]


def fingers_of(ip: str, port: int, user_id: str) -> list[int]:
    conn = connect(ip, port)
    try:
        return sorted(int(t.fid) for t in conn.get_templates() if str(t.uid) == user_id)
    finally:
        _close(conn)


def main() -> int:
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.201"
    user_id = sys.argv[2] if len(sys.argv) > 2 else "2001"
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 4370
    keep = "--keep" in sys.argv

    first = connect(ip, port)
    try:
        held = [u for u in first.get_users() if str(u.user_id) == user_id]
        if not held:
            print("The terminal is not holding user %s. Push the student to it first." % user_id)
            return 2
        print("Terminal %s, user %s is on it as %r." % (first.get_serialnumber(), user_id, held[0].name))
    finally:
        _close(first)

    before = fingers_of(ip, port, user_id)
    print("Fingerprints for %s before: %s\n" % (user_id, before or "none"))
    print("Watch the terminal's own screen. Whenever it asks for a finger, give it your right")
    print("index finger, pressing as many times as it asks. %d seconds a try.\n" % WINDOW)

    results = []
    for label, finger, form in forms(user_id):
        conn = connect(ip, port)
        try:
            conn.cancel_capture()
            answer = form(conn)
            print("%s: sent, terminal answered %s" % (label, answer), flush=True)
            heard = listen(conn, WINDOW)
        finally:
            _close(conn)
        now = fingers_of(ip, port, user_id)
        landed = finger in now and finger not in before
        results.append((label, landed, heard))
        print("      %s%s" % ("A FINGERPRINT LANDED as finger %d" % finger if landed else "nothing landed",
                               ", %d packets heard" % len(heard) if heard else ""), flush=True)
        time.sleep(2)

    print("\n==== which form the terminal obeyed ====")
    for label, landed, heard in results:
        print("%-52s %s" % (label, "WORKED" if landed else "no fingerprint"))

    made = [f for f in fingers_of(ip, port, user_id) if f not in before]
    if made and not keep:
        # Somebody's real fingerprint under a test student is not something to leave lying about.
        conn = connect(ip, port)
        try:
            for finger in made:
                # By uid: pyzk's user_id path raises struct.error over TCP.
                conn.delete_user_template(uid=int(user_id), temp_id=finger)
            conn.refresh_data()
        finally:
            _close(conn)
        print("\nThe %d fingerprint(s) this made are deleted again (pass --keep to leave them)."
              % len(made))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
