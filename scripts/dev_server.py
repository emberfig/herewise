"""Run Herewise against a scratch data folder, for looking at screens while they are built.

    python scripts/dev_server.py [port] [--fake-terminal] [--fake-network] [--reload]

Never point this at the lecturer's data. It uses ROLLCALL_DATA_DIR if that is already set, and
%TEMP%\\herewise-dev otherwise, so nothing here can touch a real register. The port is fixed rather
than "the next free one", because the browser needs to know where to look.

--fake-terminal talks to tests/fake_zk.py instead of the K40, and while a class is taking attendance
a queue scans at it, one student every couple of seconds until about three in four have. For looking
at a live class without hardware, and without a second program talking to a terminal the installed
Herewise is already watching: two programs on one terminal is a fault of its own (2026-09-22).

--fake-network puts the Connection check on a pretend laptop (tests/fake_windows.py) whose Ethernet
needs setting up, with a Windows prompt that answers No and then Yes. Without it, the Ethernet setup
on a screen is this PC's real one, and pressing it asks Windows for real.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ROLLCALL_DATA_DIR", str(Path(tempfile.gettempdir()) / "herewise-dev"))

import uvicorn  # noqa: E402

from rollcall.app import create_app  # noqa: E402
from rollcall.config import HOST  # noqa: E402


def fake_terminal(db_path: Path, reaches=None):
    """A terminal that exists only in memory, with a queue that scans while a class is open.

    With a pretend network, the heartbeat's knock asks it whether the terminal can be reached, so
    the top bar agrees with the Connection check instead of calling the terminal connected while
    the Ethernet has no address on its network.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    from fake_zk import FakeDevice, FakeRecord

    from rollcall import db, groups, live
    from rollcall.device import K40

    device = FakeDevice()

    def queue() -> None:
        while True:
            time.sleep(random.uniform(1.5, 3.5))
            try:
                conn = db.connect(db_path)
                try:
                    s = live.open_class(conn)
                    if s is None or not s["course_id"]:
                        continue
                    # The class's own register: a group's class is scanned by that group's queue.
                    members = [str(m["device_user_id"]) for m in groups.class_members(conn, s)]
                    scanned = {r.user_id for r in device.records
                               if r.timestamp.isoformat() >= s["opened_at"]}
                    left = [m for m in members if m not in scanned]
                    if left and len(scanned) < 0.75 * len(members):
                        device.records.append(FakeRecord(random.choice(left), datetime.now().replace(microsecond=0)))
                finally:
                    conn.close()
            except Exception as error:  # a development aid must never take the server down
                print(f"fake queue: {error}", flush=True)

    threading.Thread(target=queue, daemon=True).start()
    if reaches is None:
        return lambda target: K40(target, zk_factory=device.factory())
    return lambda target: K40(target, zk_factory=device.factory(), port_open=lambda: reaches(target.ip))


def fake_network() -> None:
    """A laptop whose Ethernet is on automatic with only a 169.254 address, beside a Wi-Fi, and a
    Windows prompt that answers No the first time and Yes after that. Nothing on this PC is read or
    changed: the network cards, the route, ping, the port and the prompt are all the fake's.

    The adapters carry "(pretend)" in their names, which is what scripts/drive_screens.mjs looks for
    before it presses anything that would otherwise ask Windows for administrator rights.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    from fake_windows import PRETEND, FakeWindows, ethernet, wifi

    from rollcall import diagnostics, netsetup

    windows = FakeWindows([ethernet(name="Ethernet" + PRETEND), wifi(name="Wi-Fi" + PRETEND)],
                          answers=("no", "yes"))
    diagnostics.physical_adapters = windows.read
    diagnostics.local_ipv4_addresses = windows.addresses
    diagnostics.route_source_address = windows.source_for
    diagnostics.ping = windows.reaches
    diagnostics.tcp_open = lambda ip, port, timeout=2.0: windows.reaches(ip)
    netsetup.run_elevated = windows.run
    print("using a pretend network: nothing here reads or changes this PC's adapters", flush=True)
    return windows


def build():
    folder = Path(os.environ["ROLLCALL_DATA_DIR"])
    network = fake_network() if "--fake-network" in sys.argv else None
    if "--fake-terminal" in sys.argv:
        print("using a fake terminal: nothing here talks to the K40", flush=True)
        return create_app(k40_factory=fake_terminal(folder / "rollcall.db",
                                                    reaches=network.reaches if network else None))
    return create_app()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(args[0]) if args else 8000
    folder = os.environ["ROLLCALL_DATA_DIR"]
    reload = "--reload" in sys.argv
    print(f"Herewise (development) at http://{HOST}:{port}  data: {folder}", flush=True)
    if reload:
        # Watch rollcall/ so a change to a route is picked up without stopping the browser.
        uvicorn.run("scripts.dev_server:app_factory", factory=True, host=HOST, port=port,
                    log_level="info", log_config=None, reload=True,
                    reload_dirs=[str(ROOT / "rollcall")])
    else:
        uvicorn.run(build(), host=HOST, port=port, log_level="info", log_config=None)


def app_factory():
    return build()


if __name__ == "__main__":
    main()
