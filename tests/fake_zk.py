"""A stand-in for pyzk's ZK object with just enough behaviour to test the rules around it.

It is not a protocol simulator. Real-device behaviour is checked by scripts/device_smoke.py.
"""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class FakeUser:
    uid: int
    user_id: str
    name: str
    privilege: int = 0
    password: str = ""
    group_id: str = ""
    card: int = 0


@dataclass
class FakeFinger:
    uid: int
    fid: int
    size: int = 700
    valid: int = 1


@dataclass
class FakeRecord:
    user_id: str
    timestamp: datetime
    status: int = 1
    punch: int = 255
    uid: int = 0


@dataclass
class FakeDevice:
    serial: str = "FDDW250226081"
    users: dict[int, FakeUser] = field(default_factory=dict)
    templates: dict[tuple[int, int], FakeFinger] = field(default_factory=dict)
    records: list[FakeRecord] = field(default_factory=list)
    enabled: bool = True
    clock_offset: timedelta = timedelta(0)
    user_capacity: int = 1000
    reachable: bool = True
    enroll_mode: str = "capture"            # capture | timeout | refuse | wait | stored_but_false
    # "stored_but_false" is the real K40 under pyzk: the terminal stores the finger and pyzk still
    # returns False, because it counts a press only at score 100 and this terminal sends 49 to 73.
    # "wait" holds the capture open, the way the terminal does while a student is walking up to it,
    # so cancelling one can be tested at all.
    capture_started: threading.Event = field(default_factory=threading.Event)
    capture_release: threading.Event = field(default_factory=threading.Event)
    fail: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    connections: int = 0
    open_connections: int = 0
    # Connections refused after a restart, the way the terminal is gone for about 35 seconds.
    away_for: int = 0
    # Seconds a connection takes to open, as on the owner's K40 when the clock came out 10 s slow.
    connect_delay: float = 0.0
    # A clock that ignores set_time, to prove the class window follows the terminal's clock.
    clock_stuck: bool = False
    restart_takes: int = 2
    restarts: int = 0

    def factory(self):
        return lambda target: FakeZK(self)


class FakeZK:
    def __init__(self, device: FakeDevice):
        self.device = device

    def connect(self):
        if not self.device.reachable:
            raise OSError("timed out")
        if self.device.away_for > 0:
            self.device.away_for -= 1
            raise OSError("timed out")
        if self.device.connect_delay:
            time.sleep(self.device.connect_delay)
        self.device.connections += 1
        self.device.open_connections += 1
        return FakeConn(self.device)


class FakeConn:
    def __init__(self, device: FakeDevice):
        self.d = device
        self.users = self.fingers = self.records = 0
        self.users_cap, self.fingers_cap, self.rec_cap = device.user_capacity, 2000, 80000

    def _call(self, name: str) -> None:
        self.d.calls.append(name)
        if name in self.d.fail:
            raise RuntimeError(f"{name} failed")

    def disable_device(self):
        self._call("disable_device")
        self.d.enabled = False
        return True

    def enable_device(self):
        self._call("enable_device")
        self.d.enabled = True
        return True

    def disconnect(self):
        self._call("disconnect")
        self.d.open_connections -= 1
        return True

    def read_sizes(self):
        self._call("read_sizes")
        self.users, self.fingers, self.records = len(self.d.users), len(self.d.templates), len(self.d.records)
        return True

    def get_serialnumber(self):
        return self.d.serial

    def get_firmware_version(self):
        return "Ver 6.60 Sep 10 2019"

    def get_platform(self):
        return "ZLM60_TFT"

    def get_device_name(self):
        return ""

    def get_time(self):
        return (datetime.now() + self.d.clock_offset).replace(microsecond=0)

    def set_time(self, when):
        self._call("set_time")
        if not self.d.clock_stuck:
            self.d.clock_offset = when - datetime.now()
        return True

    def get_users(self):
        self._call("get_users")
        return list(self.d.users.values())

    def set_user(self, uid=None, name="", privilege=0, password="", group_id="", user_id="", card=0):
        self._call("set_user")
        if privilege not in (0, 14):
            privilege = 0
        self.d.users[int(uid)] = FakeUser(int(uid), str(user_id), name[:24], privilege, password, group_id, card)
        return True

    def delete_user(self, uid=0, user_id=""):
        self._call("delete_user")
        self.d.users.pop(int(uid), None)
        for key in [k for k in self.d.templates if k[0] == int(uid)]:
            del self.d.templates[key]

    def delete_user_template(self, uid=0, temp_id=0, user_id=""):
        self._call("delete_user_template")
        if user_id:
            # pyzk's own line, so the fake fails where the real library fails. Over TCP with a
            # user_id it packs a str into a bytes field and raises struct.error every time
            # (zk/base.py, delete_user_template). Remove was built against a fake with no such
            # method and could never have worked on the K40 (found 2026-09-22).
            struct.pack("<24sB", str(user_id), temp_id)
        return self.d.templates.pop((int(uid), int(temp_id)), None) is not None

    def restart(self):
        self._call("restart")
        self.d.restarts += 1
        self.d.away_for = self.d.restart_takes
        self.d.open_connections -= 1
        return True

    def refresh_data(self):
        return True

    def get_templates(self):
        self._call("get_templates")
        return list(self.d.templates.values())

    def get_attendance(self):
        self._call("get_attendance")
        return list(self.d.records)

    def clear_attendance(self):
        self._call("clear_attendance")
        self.d.records.clear()
        return True

    def cancel_capture(self):
        self._call("cancel_capture")
        self.d.capture_release.set()
        return True

    def enroll_user(self, uid=0, temp_id=0, user_id=""):
        self._call("enroll_user")
        if self.d.enroll_mode == "timeout":
            raise socket.timeout("timed out")
        if self.d.enroll_mode == "refuse":
            return False
        if self.d.enroll_mode == "stored_but_false":
            self.d.templates[(int(uid), int(temp_id))] = FakeFinger(int(uid), int(temp_id))
            return False
        if self.d.enroll_mode == "wait":
            self.d.capture_started.set()
            if not self.d.capture_release.wait(10):
                raise socket.timeout("timed out")
            return False
        self.d.templates[(int(uid), int(temp_id))] = FakeFinger(int(uid), int(temp_id))
        return True
