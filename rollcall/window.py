"""The app window: Herewise in a WebView2 frame rather than a browser tab.

`python -m rollcall` starts a local server and prints an address, which is right for development
and wrong for a lecturer: a terminal window that must stay open, and a browser tab that can be
closed, bookmarked, or opened twice. The packaged app runs this instead.

What it is: the same FastAPI server on 127.0.0.1, started on a background thread, with a WebView2
window pointed at it. WebView2 is Microsoft's own Edge-based control and is already on Windows 11
and on most Windows 10 machines; when it is missing this says so in words and falls back to the
browser rather than showing nothing.

No address bar, no tabs and no developer tools, because none of them is a feature of a register.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from . import NAME, VERSION, logs
from .app import create_app
from .config import HOST, data_dir, free_port

log = logging.getLogger("rollcall")

WIDTH, HEIGHT = 1280, 800
# Below this the sheet's frozen columns give way and the drawer becomes a bottom sheet, so it is
# the smallest window the screens are designed for (design/components/living-sheet.md).
MIN_WIDTH, MIN_HEIGHT = 900, 600


class Server:
    """Uvicorn on a background thread, with a way to ask it to stop and to wait until it is up."""

    def __init__(self, port: int):
        self.port = port
        self._server = uvicorn.Server(uvicorn.Config(
            create_app(), host=HOST, port=port, log_level="warning", log_config=None))
        self._thread = threading.Thread(target=self._server.run, name="herewise-server", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self, timeout: float = 20.0) -> bool:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server.started:
                return True
            if not self._thread.is_alive():
                return False
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        started = time.monotonic()
        self._server.should_exit = True
        self._thread.join(timeout=5)
        log.info("server stopped in %.1f s%s", time.monotonic() - started,
                 "" if not self._thread.is_alive() else ", still running, left to exit with the process")


def icon_path() -> Path | None:
    path = Path(__file__).resolve().parent / "static" / "img" / "herewise.ico"
    return path if path.exists() else None


def configure(webview) -> None:
    """The two pywebview settings a register cannot work without.

    Downloads: pywebview cancels every download in its window unless told otherwise, so in the first
    build the backup, the attendance sheet, the eligibility list and every CSV did nothing at all
    when pressed, with no message. It only showed in the packaged window; the browser downloads
    them happily. Allowed, each one opens Windows' own Save dialog in the Downloads folder.

    Links out: a link with target="_blank", such as "Made by Emberfig", opens in the person's own
    browser rather than taking the register's window away to a website. That is pywebview's default,
    set here anyway so it cannot change under us in an upgrade.
    """
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True


def run() -> int:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    log_file = logs.configure(folder)
    port = free_port()
    log.info("%s %s starting on port %s, data in %s (log: %s)", NAME, VERSION, port, folder, log_file)

    server = Server(port)
    if not server.start():
        _say_plainly("Herewise could not start its own local server.",
                     "Another copy may already be running. Close it and try again.\n\n"
                     f"The log is at {log_file}.")
        return 1

    try:
        import webview
    except ImportError:
        # Packaged builds always have it; a source checkout may not.
        log.warning("pywebview is not installed, opening the browser instead")
        webbrowser.open(server.url)
        _wait_forever(server)
        return 0

    configure(webview)
    window = webview.create_window(NAME, server.url, width=WIDTH, height=HEIGHT,
                                   min_size=(MIN_WIDTH, MIN_HEIGHT), confirm_close=False)

    def opened() -> None:
        log.info("window open at %s", server.url)
        _bring_to_front(log)

    try:
        # gui="edgechromium" is WebView2. Naming it rather than letting pywebview choose means a
        # machine with an old Internet Explorer control never silently renders the app in it:
        # the screens use CSS grid, custom elements and adoptedStyleSheets, and none of that works
        # there. If WebView2 is missing it raises here, and the message below is what to do.
        webview.start(opened, gui="edgechromium", private_mode=False,
                      storage_path=str(folder / "window"), icon=str(icon_path() or ""))
        log.info("window closed")
    except Exception as error:                        # pragma: no cover, needs a machine without it
        log.exception("the window could not open")
        _say_plainly(
            "Herewise could not open its window.",
            "This needs the Microsoft Edge WebView2 Runtime, which is on Windows 11 and on most "
            "Windows 10 machines. It can be installed from Microsoft without administrator rights.\n\n"
            f"Herewise is still running, so it has been opened in your browser instead:\n{server.url}\n\n"
            f"The details are in {log_file}.\n\n{error}")
        webbrowser.open(server.url)
        _wait_forever(server)
        return 0
    finally:
        server.stop()
    return 0


def _bring_to_front(log) -> None:
    """Put the window in front of whatever is already on the screen.

    Reported on a second run: "when i open the software it opens behind open softwares or apps on
    my system" (2026-09-22). Herewise takes a few seconds to start its server and its WebView2
    window, and by then whatever the person clicked next owns the foreground. Windows refuses a
    foreground change from a process that does not already own it, so the new window goes behind.
    Measured before this: the window existed and another window was in front of it.

    Two steps, because either one alone is refused often enough to be no use. Raising the window to
    the top of the z-order needs no permission, and the topmost then not-topmost pair does that
    without leaving it pinned above everything for ever. Then the foreground is asked for with our
    input queue attached to the one that currently owns it, which is the documented way past the
    lock. If Windows still says no, it flashes the taskbar button instead, which is the right
    failure: the app is open and the person is told where.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        ours = os.getpid()
        found: list[int] = []

        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == ours and user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    found.append(int(hwnd))
            return True

        # The callback runs the moment the window is created, and on this build that is before it
        # is visible: the first attempt found nothing of this process at all and did nothing, while
        # the window went on to appear wherever Windows put it. So it waits for it, briefly.
        enum = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
        deadline = time.monotonic() + 5
        while not found and time.monotonic() < deadline:
            user32.EnumWindows(enum, 0)
            if not found:
                time.sleep(0.1)
        if not found:
            log.warning("no window of this process to bring to the front")
            return
        hwnd = found[0]

        SW_RESTORE = 9
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
        keep_size = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, keep_size)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, keep_size)

        in_front = user32.GetForegroundWindow()
        theirs = user32.GetWindowThreadProcessId(in_front, None) if in_front else 0
        mine = kernel32.GetCurrentThreadId()
        attached = bool(theirs) and theirs != mine and user32.AttachThreadInput(theirs, mine, True)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(theirs, mine, False)

        if user32.GetForegroundWindow() != hwnd:
            # Windows kept the foreground where it was. Flashing says "over here" without stealing
            # what somebody is typing into.
            FLASHW_ALL, FLASHW_TIMERNOFG = 0x00000003, 0x0000000C

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD), ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            flash = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 3, 0)
            user32.FlashWindowEx(ctypes.byref(flash))
            log.info("the window is open but Windows kept the foreground; flashed the taskbar")
        else:
            log.info("window brought to the front")
    except Exception:                                  # pragma: no cover, needs a real desktop
        log.exception("could not bring the window to the front")


def _wait_forever(server: Server) -> None:
    """With no window, the server is the app: it runs until the console is closed."""
    print(f"{NAME} is running at {server.url}. Close this window to stop it.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


def _say_plainly(heading: str, body: str) -> None:
    """A message box when there is no window yet, because a packaged app has no console to print to."""
    print(f"{heading}\n\n{body}", flush=True)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"{heading}\n\n{body}", NAME, 0x00000040)
    except Exception:                                  # pragma: no cover, not Windows
        pass


if __name__ == "__main__":
    raise SystemExit(run())
