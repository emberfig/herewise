"""A pyzatt connection dressed as a pyzk one, so the device layer can run on either library.

Why: pyzk is GPL-2.0, so distributing Herewise with it means distributing Herewise's source under the
GPL. pyzatt is MIT and speaks to the same standalone ZKTeco devices (the K40's platform, ZLM60_TFT, is
in its supported TFT family). This keeps the choice open: `rollcall/device.py` is unchanged, and
ROLLCALL_DEVICE_BACKEND=pyzatt swaps the library underneath it.

Everything the device layer calls is mapped here, and nothing else is. Differences worth knowing:

- **The internal user number is set by us, not by pyzatt.** pyzatt's `create_user` numbers a new user
  max+1, which would break the rule that uid equals user_id on every write, so this shim adds the user
  at the number it wants.
- **No comm key.** pyzatt's connect takes no password, so it only works while the Comm Key is 0, which
  is where this K40 stands. pyzk supports one.
- **Names**: pyzatt cuts at 23 characters; this shim cuts at 24 bytes, as the terminal does.
- **Attendance fields**: pyzatt gives a verification type and state; they are mapped to pyzk's punch
  and status in that order.
- **The permission byte.** The terminal keeps one byte holding the privilege and the disabled flag.
  pyzk writes and reads it whole (14 is Super Admin, verified on this K40); pyzatt splits it, taking
  the top bits as the admin level and the bottom bit as a disabled flag. Written pyzatt's way, a
  privilege of 14 becomes the byte 28 and the terminal drops the record: the user never appears. This
  shim converts both ways, so the byte on the device is the same one pyzk would write.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from datetime import datetime

BACKEND_ENV = "ROLLCALL_DEVICE_BACKEND"
NAME_LIMIT = 23
ENROLL_WAIT_SECONDS = 60      # a student has to walk to the terminal and press three times


def _decode_time(raw) -> datetime:
    """The terminal's own time encoding: months of 31 days, years of 12 such months, from 2000.

    pyzatt divides the day count by 365 instead, which put this K40's clock a whole year ahead on
    2026-09-20 (pyzk and the PC both said 2026, pyzatt said 2027). The same function timestamps every
    attendance record, so uncorrected every scan would be filed a year in the future. pyzatt's encoder
    is right; only its decoder is wrong.
    """
    value = struct.unpack("<I", raw)[0]
    second, value = value % 60, value // 60
    minute, value = value % 60, value // 60
    hour, value = value % 24, value // 24
    day, value = value % 31 + 1, value // 31
    month, value = value % 12 + 1, value // 12
    return datetime(value + 2000, month, day, hour, minute, second)


_decode_time.herewise_fix = True

# The user record the terminal stores: 72 bytes, with fixed room for each field.
_USER_RECORD, _NAME_AT, _NAME_BYTES = 72, 11, 24
_PASSWORD_AT, _PASSWORD_BYTES = 3, 8
_ID_AT, _ID_BYTES = 48, 9


def _serialise_user(user) -> bytearray:
    """Build a user record without letting a non-ASCII name corrupt it.

    pyzatt writes the name with ``record[11:11 + len(name)] = name.encode()``. For "ỌLÁBÍSÍ" len()
    counts 7 characters while encode() gives 13 bytes, so the slice grows the record past 72 bytes and
    every field after the name shifts. The terminal then drops the record without a word: on
    2026-09-20 a user with a Yoruba name never arrived, while the same push with an ASCII name did.
    Each field is cut to the room it has here, in bytes.
    """
    record = bytearray(_USER_RECORD)
    record[0:2] = struct.pack("<H", user.user_sn)
    record[2] = (user.admin_level << 1) | user.not_enabled
    def place(value: str, start: int, width: int) -> None:
        raw = str(value or "").encode("utf-8", errors="ignore")[:width]
        record[start:start + len(raw)] = raw
    place(user.user_password, _PASSWORD_AT, _PASSWORD_BYTES)
    place(user.user_name, _NAME_AT, _NAME_BYTES)
    record[35:39] = struct.pack("<I", user.card_number)
    record[39] = user.user_group
    if len(user.user_tzs) != 0:
        record[40:42] = bytes([1, 0])
        record[42:44] = struct.pack("<H", user.user_tzs[0])
        record[44:46] = struct.pack("<H", user.user_tzs[1])
        record[46:48] = struct.pack("<H", user.user_tzs[2])
    place(user.user_id, _ID_AT, _ID_BYTES)
    assert len(record) == _USER_RECORD
    return record


def patch_pyzatt() -> None:
    """Correct the two pyzatt faults this K40 showed, both in its MIT-licensed source.

    Worth sending upstream: neither is specific to Herewise.
    """
    import pyzatt.misc as misc
    from pyzatt.pyzatt import ZKUser

    if not getattr(misc.decode_time, "herewise_fix", False):
        misc.decode_time = _decode_time
    if not getattr(ZKUser.ser_user, "herewise_fix", False):
        _serialise_user.herewise_fix = True
        ZKUser.ser_user = _serialise_user


@dataclass
class _User:
    uid: int
    user_id: str
    name: str
    privilege: int
    password: str
    group_id: str
    card: int


@dataclass
class _Attendance:
    user_id: str
    timestamp: datetime
    status: int
    punch: int


@dataclass
class _Template:
    uid: int
    fid: int
    size: int


class ZattConnection:
    """The subset of pyzk's connection API that `rollcall/device.py` uses."""

    def __init__(self, session, ip: str, port: int):
        self._z = session
        self._ip, self._port = ip, port
        self.users = self.users_cap = self.fingers = self.fingers_cap = self.records = self.rec_cap = 0

    # -- session ---------------------------------------------------------------------------
    def connect(self):
        """Connect, then prove it by reading the serial.

        pyzatt's connect_net returns False on this K40 (firmware 6.60, 2019) even though the session
        works: its last step sets the SDKBuild parameter and the terminal answers 0xFFFF, which is what
        the flag ends up reflecting. Reading the serial is the honest check.
        """
        self._z.connect_net(self._ip, self._port)
        if not str(self._z.get_serial_number() or "").strip():
            raise ConnectionError(f"pyzatt could not connect to {self._ip}:{self._port}")
        return self

    def disconnect(self):
        self._z.disconnect()

    def disable_device(self):
        self._z.disable_device()

    def enable_device(self):
        self._z.enable_device()

    def refresh_data(self):
        self._z.refresh_data()

    # -- reads -----------------------------------------------------------------------------
    def get_serialnumber(self):
        return self._z.get_serial_number()

    def get_firmware_version(self):
        return self._z.get_firmware_version()

    def get_platform(self):
        return self._z.get_platform()

    def get_device_name(self):
        return self._z.get_device_info("~DeviceName")

    def get_time(self) -> datetime:
        return self._z.get_device_time()

    def set_time(self, when: datetime):
        self._z.set_device_time(when)

    def read_sizes(self):
        wanted = {"user_count": -1, "fp_count": -1, "attlog_count": -1,
                  "user_capacity": -1, "fp_capacity": -1, "attlog_capacity": -1}
        status = self._z.get_device_status(wanted)
        self.users, self.fingers, self.records = (status["user_count"], status["fp_count"],
                                                  status["attlog_count"])
        self.users_cap, self.fingers_cap, self.rec_cap = (status["user_capacity"], status["fp_capacity"],
                                                          status["attlog_capacity"])

    def get_users(self) -> list[_User]:
        self._z.read_all_user_id()
        return [_User(uid=int(sn), user_id=str(u.user_id), name=u.user_name,
                      privilege=(int(u.admin_level) << 1) | int(u.not_enabled),
                      password=u.user_password or "", group_id=str(u.user_group), card=int(u.card_number))
                for sn, u in sorted(self._z.users.items())]

    def get_templates(self) -> list[_Template]:
        self._z.read_all_user_id()
        self._z.read_all_fptmp()
        found = []
        for sn, user in sorted(self._z.users.items()):
            for index, entry in enumerate(user.user_fptmps):
                template, flag = entry
                if flag and template:
                    found.append(_Template(uid=int(sn), fid=index, size=len(template)))
        return found

    def get_attendance(self) -> list[_Attendance]:
        # pyzatt raises struct.error when the terminal holds no records: its reply has no count to read.
        try:
            self._z.read_att_log()
        except struct.error:
            return []
        return [_Attendance(user_id=str(e.user_id), timestamp=e.att_time, status=int(e.ver_state),
                            punch=int(e.ver_type)) for e in self._z.att_log]

    # -- writes ----------------------------------------------------------------------------
    def set_user(self, uid: int, name: str, privilege: int, password: str, group_id: str,
                 user_id: str, card: int = 0):
        number, byte = int(uid), int(privilege)
        self._z.add_user(number)                      # at the number we want, not pyzatt's max plus one
        self._z.users[number].set_user_info(
            user_sn=number, user_id=str(user_id), name=str(name), password=str(password or ""),
            card_no=int(card or 0), admin_lv=byte >> 1, neg_enabled=byte & 1,   # pyzatt re-joins these
            user_group=int(group_id) if str(group_id).isdigit() else 1, user_tzs=[1, 0, 0])
        self._z.upload_user_info(str(user_id))

    def delete_user(self, uid: int):
        # pyzatt deletes by user id and looks the number up in its own list, so that list is read
        # first; without it the lookup returns -1 and raises KeyError.
        self._z.read_all_user_id()
        wanted = str(int(uid))
        if any(u.user_id == wanted for u in self._z.users.values()):
            self._z.delete_user(wanted)

    def clear_attendance(self):
        self._z.clear_att_log()

    # -- enrollment ------------------------------------------------------------------------
    def enroll_user(self, uid: int, temp_id: int, user_id: str) -> bool:
        """Capture one finger, waiting as long as pyzk does.

        The socket timeout that keeps ordinary calls responsive would end a capture after a few
        seconds, before anyone could press, so it is lifted for this call and put back afterwards.
        """
        socket = self._z.soc_zk
        previous = socket.gettimeout()
        socket.settimeout(ENROLL_WAIT_SECONDS)
        try:
            return bool(self._z.enroll_user(str(user_id), int(temp_id)))
        finally:
            socket.settimeout(previous)

    def cancel_capture(self):
        self._z.cancel_capture()


class ZattDevice:
    """What `device.K40` calls: an object with connect()."""

    def __init__(self, ip: str, port: int = 4370, timeout: int = 10, password: int = 0, **_ignored):
        if password:
            raise ValueError("pyzatt cannot send a Comm Key; set it to 0 on the terminal or use pyzk.")
        self._ip, self._port, self._timeout = ip, port, timeout

    def connect(self) -> ZattConnection:
        from pyzatt.pyzatt import ZKSS

        patch_pyzatt()
        session = ZKSS()
        connection = ZattConnection(session, self._ip, self._port)
        connection.connect()
        session.soc_zk.settimeout(self._timeout)      # pyzatt leaves the socket blocking
        return connection


def factory(target) -> ZattDevice:
    return ZattDevice(target.ip, port=target.port, timeout=target.timeout, password=target.comm_key)


def chosen() -> str:
    """Which library the app talks to: pyzk by default, pyzatt when the environment says so."""
    return os.environ.get(BACKEND_ENV, "pyzk").strip().lower()
