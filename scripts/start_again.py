"""Uninstall Herewise and remove its register, so the next install starts from nothing.

**This removes somebody's register.** It is for a machine that has been used to try the app out
and is about to be used again from scratch. It prints what it found and what it removed, and stops
short of nothing: the students, the scans, the corrections, the audit log and every automatic backup
go together. The register folder goes to the Recycle Bin, not straight to nothing, so a register
removed by mistake can still be put back until the bin is emptied (changed 2026-09-24).

Asked for on 2026-09-22 after two rounds of testing: "delete all data on the app ... and uninstall
the current app so that i can install the current version".

**Run this from outside any packaged (MSIX) Windows app**, through Explorer. A packaged app's
writes to %LOCALAPPDATA% go into its own package folder, so a delete run from inside one would
leave the real register exactly where it is and report success.

It does not touch the terminal. Herewise's register and the K40's own memory are two different
things: whatever people and fingerprints are on the terminal stay on it, and are cleared from the
terminal's own screens.
"""
import ctypes
import os
import subprocess
import sys
import time
import winreg
from pathlib import Path

NAME = "Herewise"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Herewise"
LOCAL = Path(os.environ["LOCALAPPDATA"])
PROGRAM = LOCAL / "Programs" / NAME
REGISTER = LOCAL / NAME
SHORTCUT = (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / f"{NAME}.lnk")
DESKTOP = Path(os.environ["USERPROFILE"]) / "Desktop" / f"{NAME}.lnk"

lines = []


def say(text=""):
    print(text, flush=True)
    lines.append(text)


def recycle(path: Path) -> bool:
    """Send a folder to the Recycle Bin, as Explorer's own Delete does. True when it has gone."""
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 4, 16, 64, 1024
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, 0, None, None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return code == 0 and not op.fAnyOperationsAborted and not path.exists()


def running() -> bool:
    listed = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Herewise.exe", "/NH"],
                            capture_output=True, text=True).stdout
    return "Herewise.exe" in listed


def entry():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return winreg.QueryValueEx(key, "DisplayVersion")[0]
    except FileNotFoundError:
        return None


say(f"Starting again, {time.strftime('%Y-%m-%d %H:%M')}")
say(f"  LOCALAPPDATA: {LOCAL}")
say(f"  inside a packaged app? {'yes, this would not work' if 'Packages' in str(LOCAL) else 'no'}")
say()

say("1. What is here now")
say(f"  program:  {PROGRAM} {'exists' if PROGRAM.exists() else 'not there'}")
say(f"  register: {REGISTER} {'exists' if REGISTER.exists() else 'not there'}")
say(f"  uninstall entry: {entry() or 'none'}")
say()

say("2. Close it if it is running")
# Herewise and its own WebView2 processes only (/T takes the tree). Killing msedgewebview2.exe by
# name, as this did until 2026-09-24, also closed every other program on the computer built on
# WebView2, Outlook and Teams among them, with whatever they had unsaved. Asked politely first; the
# window does not answer that, so it is then closed by force, and a register in WAL mode takes that
# without harm.
was_running = running()
if was_running:
    subprocess.run(["taskkill", "/IM", "Herewise.exe", "/T"], capture_output=True, text=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and running():
        time.sleep(1)
    if running():
        subprocess.run(["taskkill", "/IM", "Herewise.exe", "/T", "/F"], capture_output=True, text=True)
        time.sleep(3)
say(f"  Herewise.exe: {'was not running' if not was_running else 'STILL RUNNING' if running() else 'closed'}")
say()

say("3. Uninstall")
uninstaller = PROGRAM / "uninstall.exe"
if uninstaller.exists():
    done = subprocess.run([str(uninstaller), "--uninstall", "--quiet"], capture_output=True, text=True)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and PROGRAM.exists():
        time.sleep(1)
    say(f"  uninstall.exe returned {done.returncode}")
else:
    say("  no uninstaller found, so nothing to run")
if PROGRAM.exists():
    # What an uninstall left behind, a file that was in use or an uninstaller already gone. Program
    # files only; the register is step 4.
    recycle(PROGRAM)
    say(f"  what was left of the program folder: {'in the Recycle Bin' if not PROGRAM.exists() else 'STILL THERE'}")
say(f"  program folder gone:   {not PROGRAM.exists()}")
say(f"  Start menu shortcut:   {'gone' if not SHORTCUT.exists() else 'still there'}")
say(f"  desktop shortcut:      {'gone' if not DESKTOP.exists() else 'still there'}")
say(f"  uninstall entry:       {'gone' if entry() is None else entry()}")
say()

say("4. The register")
if REGISTER.exists():
    recycle(REGISTER)
    time.sleep(1)
say(f"  {REGISTER}: {'in the Recycle Bin' if not REGISTER.exists() else 'STILL THERE'}")
say()

left = [str(p) for p in (PROGRAM, REGISTER, SHORTCUT, DESKTOP) if p.exists()]
if entry() is not None:
    left.append("the uninstall entry in the registry")
say("Nothing of Herewise is left on this computer." if not left
    else "STILL HERE: " + "; ".join(left))
say()
say("The terminal was not touched: whatever is on the K40 is still on it.")

report = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "start-again.txt"
report.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Written to {report}", flush=True)
