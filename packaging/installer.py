"""The Herewise installer: per user, no administrator rights, one folder.

What it does, and there is nothing else:

    copies the app into %LOCALAPPDATA%\\Programs\\Herewise
    makes a Start menu shortcut, and a desktop one if asked
    writes one uninstall entry under HKCU, so it appears in Apps and can be removed
    leaves the register alone, because that lives in %LOCALAPPDATA%\\Herewise and is not ours

It never touches Program Files, HKLM, the PATH, the registry beyond that one key, or any file
outside those two folders. That is what "no administrator rights" means here, rather than a
manifest that merely asks for fewer.

Uninstalling runs this same program with --uninstall: it removes the program folder, the shortcuts
and the uninstall entry, and says plainly that the register is being kept and where it is.

    Herewise-Setup.exe                    the installer's own window, then install
    Herewise-Setup.exe --quiet            install without asking, for several machines at once
    Herewise-Setup.exe --uninstall        ask, then remove
    Herewise-Setup.exe --uninstall --quiet
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

NAME = "Herewise"
PUBLISHER = "Emberfig"
KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{NAME}"


def bundled() -> Path:
    """The app folder carried inside this installer."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / NAME


def program_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Programs" / NAME


def register_dir() -> Path:
    """Where the app keeps the register. The installer never writes here and never deletes it."""
    return Path(os.environ["LOCALAPPDATA"]) / NAME


def start_menu() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / f"{NAME}.lnk")


def desktop() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop" / f"{NAME}.lnk"


def make_shortcut(link: Path, target: Path, icon: Path) -> bool:
    """A .lnk through PowerShell's COM, because Windows has no other way without a library."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath = '{target}';"
        "$s.WorkingDirectory = '{cwd}';"
        "$s.IconLocation = '{icon}';"
        "$s.Description = 'Lecture attendance from a fingerprint terminal';"
        "$s.Save()"
    ).format(link=link, target=target, cwd=target.parent, icon=icon)
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def write_uninstall_entry(folder: Path, version: str, size_kb: int) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        for name, value in (
            ("DisplayName", NAME),
            ("DisplayVersion", version),
            ("Publisher", PUBLISHER),
            ("InstallLocation", str(folder)),
            ("DisplayIcon", str(folder / f"{NAME}.exe")),
            ("UninstallString", f'"{folder / "uninstall.exe"}" --uninstall'),
        ):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)


def remove_uninstall_entry() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
    except FileNotFoundError:
        pass


# -- the WebView2 Runtime --------------------------------------------------------------------------
#
# Herewise's window is Microsoft's WebView2. Windows 11 has it and "the vast majority" of Windows 10
# machines do; for the rest, Microsoft's offline workflow is to check its registry value at install
# time and run the Evergreen Standalone Installer if it is missing, which installs per user when run
# without elevation (learn.microsoft.com, "Distribute your app and the WebView2 Runtime", read
# 2026-09-21). Herewise does not carry that installer inside itself: it is several times Herewise's
# own size, for a machine that is rare. A lecture theatre with no internet puts Microsoft's file
# beside this one, on the same USB stick, and this picks it up.

WEBVIEW2_CLIENT = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{WEBVIEW2_CLIENT}"),   # per machine
    (winreg.HKEY_CURRENT_USER, rf"Software\{WEBVIEW2_CLIENT}"),                # per user
)
WEBVIEW2_OFFLINE = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"


def webview2_version() -> str | None:
    """The installed WebView2 Runtime's version, or None. Either key with a real version counts."""
    for hive, path in WEBVIEW2_KEYS:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "pv")
        except OSError:
            continue
        if value and value != "0.0.0.0":
            return str(value)
    return None


def beside_installer() -> Path:
    """The folder this installer was run from, where Microsoft's offline installer may sit."""
    return Path(sys.executable).resolve().parent


def ensure_webview2() -> str:
    """Install the runtime from the file beside this installer when it is missing. Returns what the
    closing message should say about it, or nothing when all is well."""
    if webview2_version():
        return ""
    offline = beside_installer() / WEBVIEW2_OFFLINE
    if offline.exists():
        try:
            # Not elevated, so it installs for this user only: no administrator prompt, as promised.
            subprocess.run([str(offline), "/silent", "/install"], check=False, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
        if webview2_version():
            return ("The Microsoft Edge WebView2 Runtime, which draws Herewise's window, was "
                    "installed from the file beside this installer.")
        return ("The Microsoft Edge WebView2 Runtime could not be installed from the file beside "
                "this installer, so Herewise will open in your web browser instead of its own "
                "window. Everything works the same there.")
    return ("This computer does not have the Microsoft Edge WebView2 Runtime, which draws Herewise's "
            "window, so Herewise will open in your web browser instead. Everything works the same "
            f"there. To give it its own window, put Microsoft's offline installer, {WEBVIEW2_OFFLINE}, "
            "beside this installer and run this installer again.")


def holds_a_register(folder: Path) -> bool:
    """True when the program folder has been made portable and keeps the register inside itself.

    Installing over the folder or removing it deletes everything in it, so a register kept there
    would go with it. The installer never makes a folder portable, but a person following the
    instructions for a USB copy might, and scans, corrections and the audit log cannot be got back.
    """
    return (folder / "portable").exists() or (folder / "rollcall.db").exists()


def version_of(folder: Path) -> str:
    """The version the app folder carries. A one-folder PyInstaller build puts its data files
    under _internal, so that is where the marker actually lands; the root is checked too in case
    a later build lays them out differently. Without this the uninstall entry read 0.0.0."""
    for marker in (folder / "_internal" / "VERSION", folder / "VERSION"):
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip()
    return "0.0.0"


# -- installing ---------------------------------------------------------------------------------
#
# The work is done by do_install and do_uninstall, which report progress to whoever asks and raise
# Refused with the words to show. Two things show them: the installer's own window
# (installer_window.py, asked for on 2026-09-23 after two plain message boxes), and the message
# boxes and console below, for --quiet and for a machine without the WebView2 Runtime to draw a
# window with.

Progress = Callable[[str, int, int, str], None]      # step, done, total, what is happening


class Refused(Exception):
    """Nothing was changed, and this is why. ``code`` lets the window offer the right way out."""

    def __init__(self, heading: str, body: str, code: str = "refused"):
        super().__init__(heading)
        self.heading, self.body, self.code = heading, body, code


def _quietly(step: str, done: int, total: int, detail: str) -> None:
    pass


def installed_version() -> str | None:
    """The version the uninstall entry names, so an update can say what it is updating from."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            return str(winreg.QueryValueEx(key, "DisplayVersion")[0])
    except OSError:
        return None


def previous_version() -> str | None:
    """What is installed now: the uninstall entry, or else the program folder's own VERSION file.

    The entry alone was not enough. On 2026-09-23 the owner's machine had 0.1.6 in its folder, with
    both shortcuts, and no uninstall entry, so the 0.1.7 installer called itself a fresh install. The
    folder is the program; the entry only describes it.
    """
    if not program_dir().exists():
        return None
    named = installed_version()
    if named:
        return named
    found = version_of(program_dir())
    return found if found != "0.0.0" else None


def running_copies() -> list[int]:
    """The process ids of Herewise running from the program folder, and nothing else."""
    target = program_dir()
    script = (f"Get-Process -Name {NAME} -ErrorAction SilentlyContinue | "
              f"Where-Object {{ $_.Path -like '{target}\\*' }} | ForEach-Object {{ $_.Id }}")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(line) for line in done.stdout.split() if line.strip().isdigit()]


def close_running() -> int:
    """Close Herewise so it can be replaced. It writes every change as it happens, so closing it
    loses nothing; a class taking attendance stays open and carries on when it is opened again."""
    ids = running_copies()
    for pid in ids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Windows lets go of a closed program's files a moment after it ends, and renaming the folder
    # before then fails exactly as if it were still open.
    for _ in range(20):
        if not ids or not running_copies():
            break
        time.sleep(0.5)
    time.sleep(1 if ids else 0)
    return len(ids)


def do_install(with_desktop: bool, progress: Progress = _quietly) -> dict:
    source = bundled()
    if not source.exists():
        raise Refused("This installer is incomplete.",
                      "The program files are missing from it. Download it again.", "incomplete")

    target = program_dir()
    replacing = target.exists()
    previous = previous_version() if replacing else None
    if replacing and holds_a_register(target):
        raise Refused(KEEPS_ITS_REGISTER, register_inside(target), "portable")

    files = [f for f in source.rglob("*") if f.is_file()]
    total = len(files) + 4
    progress("prepare", 0, total, "Getting ready")
    if replacing:
        # An upgrade replaces the program and leaves the register untouched. The old folder is
        # moved aside first because renaming a folder fails while anything in it is running, and
        # fails having changed nothing. Deleting in place could get half way and leave a program
        # that no longer starts.
        old = target.with_name(f"{NAME}.old")
        shutil.rmtree(old, ignore_errors=True)
        try:
            target.rename(old)
        except OSError:
            raise Refused(f"{NAME} is still running.",
                          f"Close the {NAME} window and run this installer again. Nothing has been "
                          "changed.", "running") from None
        shutil.rmtree(old, ignore_errors=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    copied = 0

    def copy(src, dst, *, follow_symlinks=True):
        nonlocal copied
        shutil.copy2(src, dst, follow_symlinks=follow_symlinks)
        copied += 1
        if copied % 25 == 0 or copied == len(files):
            progress("copy", copied, total, f"Copying files, {copied:,} of {len(files):,}")
        return dst

    progress("copy", 0, total, f"Copying files, 0 of {len(files):,}")
    shutil.copytree(source, target, copy_function=copy)
    shutil.copy2(sys.executable, target / "uninstall.exe")

    exe = target / f"{NAME}.exe"
    icon = target / "_internal" / "rollcall" / "static" / "img" / "herewise.ico"
    if not icon.exists():
        icon = exe
    progress("shortcuts", len(files) + 1, total, "Making the shortcuts")
    made_start = make_shortcut(start_menu(), exe, icon)
    if with_desktop:
        make_shortcut(desktop(), exe, icon)

    progress("entry", len(files) + 2, total, "Adding Herewise to Installed apps")
    size_kb = sum(f.stat().st_size for f in target.rglob("*") if f.is_file()) // 1024
    version = version_of(target)
    write_uninstall_entry(target, version, size_kb)
    progress("runtime", len(files) + 3, total, "Checking the window runtime")
    runtime = ensure_webview2()
    progress("done", total, total, "Done")

    where = "the Start menu" if made_start else str(exe)
    return {
        "heading": f"{NAME} is installed." if not replacing else f"{NAME} is updated.",
        "body": (f"Open it from {where}.\n\n"
                 f"The program is in {target}.\n"
                 f"The register is kept separately, in {register_dir()}, and is never touched by "
                 "installing or removing the program." + (f"\n\n{runtime}" if runtime else "")),
        "replacing": replacing, "previous": previous, "version": version, "runtime": runtime,
        "start_menu": made_start, "desktop": with_desktop, "exe": str(exe),
    }


def install(with_desktop: bool) -> int:
    try:
        done = do_install(with_desktop)
    except Refused as refusal:
        return refuse(refusal.heading, refusal.body)
    return say(done["heading"], done["body"], start=Path(done["exe"]))


# -- removing -----------------------------------------------------------------------------------

KEEPS_ITS_REGISTER = f"This copy of {NAME} keeps its register inside the program folder."


def register_inside(folder: Path) -> str:
    return (f"{folder} has been set up to run portably, so the attendance records are in it, and "
            "replacing or removing the folder would delete them.\n\n"
            "Nothing has been changed. Take a backup from the app first, or move rollcall.db out of "
            "that folder, then run this again.")


def do_uninstall(progress: Progress = _quietly) -> dict:
    """Everything but the program folder itself, which remove_folder_after_exit takes."""
    target = program_dir()
    if holds_a_register(target):
        raise Refused(KEEPS_ITS_REGISTER, register_inside(target), "portable")
    # Here and not only in the window, so --quiet and the message boxes ask as well. Without it a
    # removal against an open Herewise took the entry and the shortcuts and could not take the
    # locked folder, which Windows then no longer listed anywhere (2026-09-24).
    if running_copies():
        raise Refused(f"{NAME} is still running.",
                      f"Close the {NAME} window and remove it again. Nothing has been changed.",
                      "running")
    progress("shortcuts", 1, 3, "Removing the shortcuts")
    for link in (start_menu(), desktop()):
        try:
            link.unlink(missing_ok=True)
        except OSError:
            pass
    progress("entry", 2, 3, "Taking Herewise out of Installed apps")
    remove_uninstall_entry()
    progress("done", 3, 3, "Done")
    return {"heading": f"{NAME} has been removed.",
            "body": (f"Your register has been kept, in {register_dir()}. Delete that folder yourself "
                     "if you want the attendance records gone as well, and keep a backup first if "
                     "there is any chance you will want them."),
            "register": str(register_dir()), "register_exists": register_dir().exists()}


def remove_folder_after_exit() -> None:
    """Delete the program folder once this process, which runs from inside it, has ended.

    It waits for the process rather than for a fixed time. It used to wait two seconds and then
    delete, while the closing message was still on the screen: anybody who read it for longer than
    that left uninstall.exe running, the delete skipped the locked file, and the folder stayed.
    A one-file build is two processes, the bootloader and this one, and both hold the file.
    """
    target = program_dir()
    if not target.exists():
        return
    ids = ",".join(str(p) for p in {os.getpid(), os.getppid()})
    script = (f"Wait-Process -Id {ids} -Timeout 600 -ErrorAction SilentlyContinue; "
              f'Start-Sleep -Seconds 1; Remove-Item -LiteralPath "{target}" '
              "-Recurse -Force -ErrorAction SilentlyContinue")
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         cwd=tempfile.gettempdir(),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError:
        pass


def uninstall() -> int:
    try:
        done = do_uninstall()
    except Refused as refusal:
        return refuse(refusal.heading, refusal.body)
    remove_folder_after_exit()
    return say(done["heading"], done["body"])


# -- talking to the person ----------------------------------------------------------------------

QUIET = "--quiet"


def quiet() -> bool:
    return QUIET in sys.argv


def ask(heading: str, body: str) -> bool:
    if quiet():
        print(f"{heading}\n\n{body}")
        return True
    try:
        import ctypes
        # 1 is OK and Cancel, 0x40 the information icon.
        return ctypes.windll.user32.MessageBoxW(None, f"{heading}\n\n{body}", NAME, 0x41) == 1
    except Exception:
        print(f"{heading}\n\n{body}")
        return input("Carry on? [Y/n] ").strip().lower() in ("", "y", "yes")


def refuse(heading: str, body: str) -> int:
    """Says why nothing was done, and exits non-zero so a script installing on several machines
    with --quiet can tell a refusal from a success."""
    say(heading, body)
    return 1


def say(heading: str, body: str, start: Path | None = None) -> int:
    if quiet():
        print(f"{heading}\n\n{body}")
        return 0
    try:
        import ctypes
        if start is not None:
            # 4 is Yes and No.
            answer = ctypes.windll.user32.MessageBoxW(
                None, f"{heading}\n\n{body}\n\nOpen it now?", NAME, 0x44)
            if answer == 6:
                os.startfile(start)                                   # noqa: S606
            return 0
        ctypes.windll.user32.MessageBoxW(None, f"{heading}\n\n{body}", NAME, 0x40)
    except Exception:
        print(f"{heading}\n\n{body}")
    return 0


def plain(uninstalling: bool) -> int:
    """The message boxes, for --quiet and for a machine the window cannot be drawn on."""
    if uninstalling:
        if not ask(f"Remove {NAME}?",
                   f"The program is removed from {program_dir()}.\n\n"
                   f"Your register in {register_dir()} is kept."):
            return 0
        return uninstall()
    if not ask(f"Install {NAME}?",
               f"It goes in {program_dir()}, which belongs to you, so this needs no administrator "
               "rights and changes nothing for anyone else who uses this computer.\n\n"
               "A shortcut is put in the Start menu and on the desktop."):
        return 0
    return install(with_desktop=not quiet())


def main() -> int:
    if os.name != "nt":
        print(f"{NAME} is a Windows program.")
        return 1
    uninstalling = "--uninstall" in sys.argv
    if not quiet() and webview2_version():
        try:
            import installer_window                   # packaging/installer_window.py
        except ImportError:
            installer_window = None
        if installer_window is not None:
            # This module as an object: __main__ in the build, but not registered at all when loaded
            # from its path, and a KeyError here was once swallowed by the fallback below.
            this = sys.modules.get(__name__) or SimpleNamespace(**globals())
            try:
                return installer_window.run(this, uninstalling)
            except installer_window.NoWindow:
                pass                                  # drawn nothing yet, so the boxes take over
    return plain(uninstalling)


if __name__ == "__main__":
    raise SystemExit(main())
