"""Types into `reset-password`'s console the way a person would, and reports what happened.

    python scripts/check_reset_console.py <command...>

    python scripts/check_reset_console.py dist\\Herewise\\Herewise.exe
    python scripts/check_reset_console.py <base pythonw.exe> packaging\\launch.py

It makes a register in a scratch folder with one owner, starts the command with
`reset-password owner`, attaches to the console that opens, types a new password twice through
WriteConsoleInputW, reads the console's screen back, and signs in. It prints one line of JSON:
whether the password was ever on screen, the exit code, and the sign-in results. Windows only.

Why it exists: a windowed program has no console, so the reset opens one, and getpass hides what is
typed only when stdin is the process's original stdin. Leaving that out echoed the password in plain
text, which this caught when it was broken on purpose (2026-09-21). tests/test_reset_console.py runs
it against the source launcher.

It detaches from its own console to attach to the child's, so run it as its own process, never
inside another program that needs its console afterwards. A venv's python.exe and pythonw.exe are
redirectors that start the real interpreter as a child, so give it the base interpreter; the console
would belong to a grandchild otherwise.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLD, NEW = "forgotten-pass-1", "fresh-pass-2026"
KEY_EVENT = 0x0001
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                ("uChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]


class _EVENT(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("Event", _EVENT)]


class COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


def main(command: list[str]) -> dict:
    from fastapi.testclient import TestClient

    from rollcall.app import create_app

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE

    def handle(name: str):
        return k32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               None, OPEN_EXISTING, 0, None)

    def type_text(text: str) -> None:
        records = (INPUT_RECORD * (len(text) * 2))()
        for i, ch in enumerate(text):
            vk = 0x0D if ch == "\r" else ctypes.windll.user32.VkKeyScanW(ch) & 0xFF
            for j, down in enumerate((True, False)):
                key = records[i * 2 + j]
                key.EventType = KEY_EVENT
                key.Event.KeyEvent.bKeyDown = down
                key.Event.KeyEvent.wRepeatCount = 1
                key.Event.KeyEvent.wVirtualKeyCode = vk
                key.Event.KeyEvent.uChar = ch
        written = wintypes.DWORD()
        conin = handle("CONIN$")
        k32.WriteConsoleInputW(conin, records, len(records), ctypes.byref(written))
        k32.CloseHandle(conin)

    def screen() -> str:
        conout = handle("CONOUT$")
        width, rows = 120, 40
        buffer = ctypes.create_unicode_buffer(width * rows)
        read = wintypes.DWORD()
        k32.ReadConsoleOutputCharacterW(conout, buffer, width * rows, COORD(0, 0), ctypes.byref(read))
        k32.CloseHandle(conout)
        text = buffer.value[:read.value]
        return "\n".join(text[i:i + width].rstrip() for i in range(0, len(text), width)).strip()

    def wait_for(words: str, timeout: float = 30) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            seen = screen()
            if words in seen:
                return seen
            time.sleep(0.2)
        raise TimeoutError(f"never saw {words!r}; the screen said: {screen()!r}")

    data = Path(tempfile.mkdtemp(prefix="herewise-reset-"))
    db_path = data / "rollcall.db"
    with TestClient(create_app(db_path)) as client:
        client.post("/api/setup", json={"username": "owner", "display_name": "Only Owner",
                                        "password": OLD, "academic_session": "2026/2027"})

    env = dict(os.environ, ROLLCALL_DATA_DIR=str(data))
    child = subprocess.Popen(command + ["reset-password", "owner"], env=env)
    result = {"exit_code": None, "password_on_screen": None, "screen": ""}
    try:
        k32.FreeConsole()
        deadline = time.monotonic() + 30
        while not k32.AttachConsole(child.pid):
            if time.monotonic() > deadline or child.poll() is not None:
                raise TimeoutError(f"no console to attach to (exit {child.poll()})")
            time.sleep(0.2)
        wait_for("New password:")
        type_text(NEW + "\r")
        wait_for("Type it again:")
        type_text(NEW + "\r")
        seen = wait_for("Press Enter to close this window.")
        type_text("\r")
        k32.FreeConsole()
        result.update(exit_code=child.wait(timeout=20), password_on_screen=NEW in seen, screen=seen)
    except TimeoutError as error:
        result["error"] = str(error)
        child.kill()

    with TestClient(create_app(db_path)) as client:
        result["new_password_signs_in"] = client.post(
            "/api/login", json={"username": "owner", "password": NEW}).status_code == 200
        result["old_password_signs_in"] = client.post(
            "/api/login", json={"username": "owner", "password": OLD}).status_code == 200
        entries = client.get("/api/audit").json()["entries"] if result["new_password_signs_in"] else []
        result["audit"] = [e.get("sentence") for e in entries[:1]]
    return result


if __name__ == "__main__":
    if os.name != "nt" or len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(main(sys.argv[1:])))
