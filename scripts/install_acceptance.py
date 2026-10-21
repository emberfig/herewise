"""Install, run, upgrade and remove the built Herewise, and say where everything actually landed.

    python scripts/install_acceptance.py [--installer dist\\Herewise-Setup-0.1.0.exe]

**Run this from outside any packaged (MSIX) Windows app**, such as a terminal inside one. A packaged
app's writes to %LOCALAPPDATA% are redirected into its own package folder, so an install tested
inside it proves nothing about where the program, the shortcut and the uninstall entry really go.
Launch it through Explorer, which starts it outside the container:

    explorer.exe build\\run-install-acceptance.cmd

It writes everything it found to `build/install-acceptance-<when>.log` and prints the same, and
exits 1 on the first thing that is not as it should be.

**`--window-only` runs steps 3, 4 and 5 alone, against `dist/Herewise`, and installs nothing.** Use it
on a machine that already has somebody's Herewise on it with a real register: the full run installs
over their copy, starts the new build against their register, which migrates it, and uninstalls
their copy at the end. The packaged download is the part of this that can only be seen by driving
the real window, so it is worth checking on its own.

What it checks, in order:

1. a clean machine: nothing installed, and any register from an earlier run left alone;
2. install with --quiet: exit code, the program folder, the version on the exe, the Start menu
   shortcut, the HKCU uninstall entry, and no desktop shortcut (--quiet does not make one);
3. the installed app runs: it serves its own pages on the port it logged, and its About screen
   reads the version from the same place the installer did;
4. **a download in the packaged window**, which is the thing no test can see: the window is driven
   over the DevTools protocol to press Download a backup, and this script watches for Windows' own
   Save dialog to appear. In build 0.1.0 pywebview cancelled every download silently, so nothing at
   all happened when it was pressed;
5. **the window put itself in front**, read from the app's own log: it opened behind whatever was
   already on the screen, because Windows refuses a foreground change from a process that does not
   already own it and Herewise takes seconds to start (2026-09-22);
6. a register in the default folder survives an upgrade and a removal;
7. upgrade: the same installer run again over the installed copy replaces it;
8. remove: `uninstall.exe --uninstall --quiet` takes the folder, the shortcut and the entry away,
   and leaves the register where it is.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "Herewise"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Herewise"
DEBUG_PORT = 9334
NODE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"

failures: list[str] = []
lines: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    lines.append(text)


def check(ok: bool, what: str, detail: str = "") -> bool:
    say(f"  {'PASS' if ok else 'FAIL'}  {what}{f': {detail}' if detail else ''}")
    if not ok:
        failures.append(what)
    return ok


def local_app_data() -> Path:
    # Read from the environment rather than a guess, because the whole point of this script is
    # which %LOCALAPPDATA% it is running against.
    return Path(os.environ["LOCALAPPDATA"])


def program_folder() -> Path:
    return local_app_data() / "Programs" / NAME


def register_folder() -> Path:
    return local_app_data() / NAME


def start_menu_shortcut() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / f"{NAME}.lnk")


def desktop_shortcut() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop" / f"{NAME}.lnk"


def uninstall_entry() -> dict | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            out = {}
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                out[name] = value
            return out
    except FileNotFoundError:
        return None


def exe_version(path: Path) -> str:
    script = ("(Get-Item -LiteralPath $env:HW_FILE).VersionInfo.FileVersion")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, env={**os.environ, "HW_FILE": str(path)})
    return result.stdout.strip()


def shortcut_target(path: Path) -> str:
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:HW_LNK); $s.TargetPath")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, env={**os.environ, "HW_LNK": str(path)})
    return result.stdout.strip()


# -- the Save dialog -----------------------------------------------------------------------------

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010
ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def top_level_dialogs() -> dict[int, str]:
    """Every visible top-level window of the standard dialog class, by handle and title."""
    found: dict[int, str] = {}

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value != "#32770":
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        found[int(hwnd)] = title.value
        return True

    user32.EnumWindows(ENUM_PROC(visit), 0)
    return found


# -- the app -------------------------------------------------------------------------------------

def port_from_log(folder: Path, timeout: float = 40) -> int | None:
    log = folder / "logs" / "herewise.log"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.exists():
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
                if "starting on port" in line:
                    return int(line.split("starting on port")[1].split(",")[0].strip())
        time.sleep(0.5)
    return None


def serves(port: int, path: str = "/", timeout: float = 30) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as answer:
                return answer.read().decode("utf-8", "replace")
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return None


# Which built copy to run. Normally the installed one, because that is what this script is about;
# --window-only points it at dist/Herewise so the packaged window can be checked on a machine that
# already has somebody's Herewise installed, without touching it.
APP_EXE: Path | None = None


def app_exe() -> Path:
    return APP_EXE or (program_folder() / f"{NAME}.exe")


def start_app(data_folder: Path, debug: bool) -> subprocess.Popen:
    env = {**os.environ, "ROLLCALL_DATA_DIR": str(data_folder)}
    if debug:
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={DEBUG_PORT}"
    return subprocess.Popen([str(app_exe())], env=env)


def stop(process: subprocess.Popen) -> None:
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   capture_output=True, text=True)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    # The window's own process can outlive the launcher by a few seconds while the server stops.
    time.sleep(3)


def runs_and_downloads(scratch: Path) -> None:
    """Steps 3 and 4: the built app runs, and a download in its window reaches Windows' own Save
    dialog. Shared, because --window-only runs exactly these two against dist/Herewise."""
    say("3. The installed app runs")
    app_data = scratch / "data"
    process = start_app(app_data, debug=True)
    port = port_from_log(app_data)
    check(port is not None, "it wrote the port it is serving on to its log", str(port))
    body = serves(port) if port else None
    check(bool(body and "herewise" in body.lower()), "it serves its own front page")
    about = serves(port, "/api/setup/status") if port else None
    check(about is not None, "its API answers", (about or "")[:80])
    say()

    say("4. A download in the packaged window")
    before = set(top_level_dialogs())
    driven = {}
    if port:
        result = subprocess.run([NODE, str(ROOT / "scripts" / "window_download.mjs"),
                                 str(port), str(DEBUG_PORT)], capture_output=True, text=True)
        try:
            driven = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            driven = {"error": (result.stdout + result.stderr).strip()[-400:]}
    check(driven.get("pressed") is True, "the window was driven to press Download a backup",
          json.dumps(driven)[:300])
    dialog = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and dialog is None:
        for handle, title in top_level_dialogs().items():
            if handle not in before:
                dialog = (handle, title)
                break
        time.sleep(0.5)
    check(dialog is not None, "Windows' own Save dialog opened", dialog[1] if dialog else
          "nothing opened, so the download was cancelled as it was in build 0.1.0")
    if dialog:
        user32.PostMessageW(dialog[0], WM_CLOSE, 0, 0)
        time.sleep(1)
    say()

    # 5. the window put itself in front of whatever was already on the screen. Reported on a second
    # run: it opened behind other windows, because Windows refuses a foreground change from a
    # process that does not already own it and Herewise takes seconds to start. Read from the app's
    # own log rather than from the screen: whether Windows granted it depends on what was in front
    # at that moment, and what this checks is that the code ran and said which way it went.
    say("5. The window in front")
    log = (app_data / "logs" / "herewise.log")
    said = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    forward = "window brought to the front" in said
    flashed = "kept the foreground" in said
    check(forward or flashed, "it brought its window forward, or flashed the taskbar instead",
          "brought forward" if forward else "flashed" if flashed else said[-160:])
    stop(process)
    say()


def window_only(scratch: Path, log_file: Path) -> int:
    """The packaged window only: no install, no uninstall, no register but a scratch one. For a
    machine that already has somebody's Herewise on it, where the full run would uninstall their
    copy and start the new build against their register."""
    exe = app_exe()
    say(f"Only the packaged window, against {exe}")
    say()
    if not exe.exists():
        say(f"No built app at {exe}. Build one first: python packaging/build.py")
        return 2
    check(exe_version(exe).startswith("0."), "the built exe carries a version", exe_version(exe))
    say()
    runs_and_downloads(scratch)
    shutil.rmtree(scratch, ignore_errors=True)
    say()
    say("FAILED: " + "; ".join(failures) if failures else "Everything above passed.")
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(f"Written to {log_file}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", default=None)
    parser.add_argument("--keep", action="store_true", help="leave it installed at the end")
    parser.add_argument("--window-only", action="store_true",
                        help="run only steps 3 and 4, against dist/Herewise, installing nothing")
    args = parser.parse_args()

    global APP_EXE
    if args.window_only:
        APP_EXE = ROOT / "dist" / NAME / f"{NAME}.exe"

    # The newest by modification time, not the first in alphabetical order: with 0.1.0 and 0.1.1
    # both in dist/, sorting by name picks 0.1.0 and the run accepts the build before the one just
    # made (2026-09-22). The line below prints whichever it chose.
    installer = Path(args.installer) if args.installer else next(
        iter(sorted((ROOT / "dist").glob(f"{NAME}-Setup-*.exe"),
                    key=lambda p: p.stat().st_mtime, reverse=True)), None)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = ROOT / "build" / f"install-acceptance-{stamp}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    say(f"Herewise install acceptance, {datetime.now():%Y-%m-%d %H:%M}")
    say(f"  installer:  {installer}")
    say(f"  LOCALAPPDATA: {local_app_data()}")
    say(f"  inside a packaged app? {'yes, these results are worthless' if 'Packages' in str(local_app_data()) else 'no'}")
    say()

    if installer is None or not installer.exists():
        say("No installer found in dist/. Build one first: python packaging/build.py")
        return 2

    scratch = Path(os.environ["TEMP"]) / f"herewise-acceptance-{stamp}"
    scratch.mkdir(parents=True, exist_ok=True)

    if args.window_only:
        return window_only(scratch, log_file)

    say("1. Before anything")
    check(not program_folder().exists(), "nothing is installed yet", str(program_folder()))
    register_existed = register_folder().exists()
    say(f"  note  a register folder {'exists already' if register_existed else 'does not exist yet'}: {register_folder()}")
    say()

    say("2. Install, quietly")
    result = subprocess.run([str(installer), "--quiet"], capture_output=True, text=True)
    check(result.returncode == 0, "the installer returned 0", result.stdout.strip()[-200:] or result.stderr.strip()[-200:])
    exe = program_folder() / f"{NAME}.exe"
    check(exe.exists(), "the program is in the per-user program folder", str(exe))
    check(exe_version(exe).startswith("0."), "the exe carries a version", exe_version(exe))
    check(start_menu_shortcut().exists(), "there is a Start menu shortcut", str(start_menu_shortcut()))
    if start_menu_shortcut().exists():
        target = shortcut_target(start_menu_shortcut())
        check(Path(target) == exe, "the shortcut points at the installed exe", target)
    check(not desktop_shortcut().exists(), "--quiet made no desktop shortcut", str(desktop_shortcut()))
    entry = uninstall_entry()
    check(entry is not None, "there is one uninstall entry under HKCU")
    if entry:
        check(entry.get("DisplayVersion", "") == exe_version(exe).rsplit(".", 1)[0]
              or entry.get("DisplayVersion", "") in exe_version(exe),
              "the uninstall entry's version matches the exe", str(entry.get("DisplayVersion")))
        check("Programs" in str(entry.get("UninstallString", "")),
              "the uninstall entry points into the program folder", str(entry.get("UninstallString")))
    say()

    runs_and_downloads(scratch)

    say("5. A register in the default folder")
    process = start_app(register_folder(), debug=False)
    default_port = port_from_log(register_folder())
    check(default_port is not None, "it starts against its own data folder", str(default_port))
    serves(default_port) if default_port else None
    stop(process)
    database = register_folder() / "rollcall.db"
    check(database.exists(), "a register was made where the app keeps it", str(database))
    before_size = database.stat().st_size if database.exists() else 0
    say()

    say("6. Upgrade over the installed copy")
    result = subprocess.run([str(installer), "--quiet"], capture_output=True, text=True)
    check(result.returncode == 0, "the installer ran again and returned 0",
          result.stdout.strip()[-200:] or result.stderr.strip()[-200:])
    check(exe.exists(), "the program is still there")
    check(database.exists() and database.stat().st_size == before_size,
          "the register was not touched by the upgrade")
    say()

    if args.keep:
        say("7. Left installed, as asked")
    else:
        say("7. Remove")
        uninstaller = program_folder() / "uninstall.exe"
        check(uninstaller.exists(), "there is an uninstaller beside the program")
        result = subprocess.run([str(uninstaller), "--uninstall", "--quiet"],
                                capture_output=True, text=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and program_folder().exists():
            time.sleep(1)
        check(result.returncode == 0, "the uninstaller returned 0",
              result.stdout.strip()[-200:] or result.stderr.strip()[-200:])
        check(not program_folder().exists(), "the program folder is gone", str(program_folder()))
        check(not start_menu_shortcut().exists(), "the Start menu shortcut is gone")
        check(uninstall_entry() is None, "the uninstall entry is gone")
        check(database.exists(), "the register is still there", str(database))
    say()

    if not register_existed and not args.keep:
        # This script made that register. It does not leave one behind on somebody's machine.
        shutil.rmtree(register_folder(), ignore_errors=True)
        say(f"Removed the register this run made: {register_folder()}")
    shutil.rmtree(scratch, ignore_errors=True)

    say()
    say(f"{'FAILED: ' + '; '.join(failures) if failures else 'Everything above passed.'}")
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    say(f"Written to {log_file}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
