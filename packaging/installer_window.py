"""The installer's own window: Herewise's colours, type and logo, in the same WebView2 the app uses.

Asked for on 2026-09-23, with screenshots of the two plain Windows message boxes the installer had
been: "I want you to create a professional install interface for Herewise". The work is still done
by packaging/installer.py (do_install, do_uninstall); this draws it and reports it as it happens.
The page is packaging/installer_ui/, with the app's tokens, base styles and fonts copied in beside
it by stage_ui, so the installer cannot drift from the program it installs.

The message boxes stay, for --quiet and for a machine without the WebView2 Runtime, which is what
would draw this. installer.main only comes here when the runtime is present, and NoWindow sends it
back to the boxes if the window still cannot be made.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import winreg
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE / "installer_ui"
WIDTH, HEIGHT = 720, 480


class NoWindow(Exception):
    """The window could not be drawn and nothing has been done, so the message boxes can take over."""


def stage_ui(dest: Path, root: Path | None = None, preview: bool = False) -> Path:
    """The page, with the app's own tokens, base styles, fonts and licences beside it.

    ``preview`` keeps preview.js, a stand-in for this module that lets the page be looked at in a
    browser, screen by screen. It never goes into a build.
    """
    root = root or HERE.parent
    static = root / "rollcall" / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(UI, dest, ignore=None if preview else shutil.ignore_patterns("preview.js"))
    (dest / "css").mkdir(exist_ok=True)
    for name in ("tokens.css", "base.css"):
        shutil.copy2(static / "css" / name, dest / "css" / name)
    shutil.copytree(static / "fonts", dest / "fonts")
    return dest


def ui_dir() -> Path:
    """Where the page is: inside the one-file build, or staged from the source tree."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "installer_ui"
    return stage_ui(Path(tempfile.mkdtemp(prefix="herewise-setup-")) / "installer_ui")


def light_theme() -> bool:
    """Windows' own app theme, so the window is not white for a moment before a dark page paints."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except OSError:
        return True


class Api:
    """What the page may call. Every public method here is reachable from its JavaScript, so there
    are only the ones the screens need, and the window is kept in an underscored attribute because
    pywebview walks the public ones."""

    def __init__(self, installer, uninstalling: bool):
        self._installer = installer
        self._mode = "remove" if uninstalling else "install"
        self._window = None
        self._busy = False
        self._removed = False
        self._installed_exe: str | None = None

    # -- what the page asks for ------------------------------------------------------------------

    def info(self) -> dict:
        i = self._installer
        version = i.version_of(i.bundled()) if i.bundled().exists() else "unknown"
        if self._mode == "remove":
            version = i.version_of(i.program_dir())
        return {
            "mode": self._mode,
            "version": version,
            "previous": i.previous_version(),
            "program_dir": str(i.program_dir()),
            "register_dir": str(i.register_dir()),
            "register_exists": i.register_dir().exists(),
        }

    def install(self, with_desktop: bool) -> None:
        self._run(lambda: self._installer.do_install(bool(with_desktop), self._progress), "install")

    def uninstall(self) -> None:
        def work():
            self._progress("check", 0, 3, "Checking Herewise is closed")
            done = self._installer.do_uninstall(self._progress)      # refuses while it is running
            self._removed = True
            return done
        self._run(work, "remove")

    def close_running(self) -> int:
        return self._installer.close_running()

    def open_app(self) -> None:
        if self._installed_exe:
            os.startfile(self._installed_exe)                         # noqa: S606
        self.close()

    def open_register(self) -> None:
        folder = self._installer.register_dir()
        if folder.exists():
            os.startfile(folder)                                      # noqa: S606

    def close(self) -> None:
        if not self._busy and self._window is not None:
            self._window.destroy()

    # -- doing the work off the window's thread ----------------------------------------------------

    def _run(self, work, mode: str) -> None:
        if self._busy:
            return
        self._busy = True

        def body():
            try:
                result = work()
                if mode == "install":
                    self._installed_exe = result.get("exe")
                self._call("finished", {**result, "mode": mode})
            except self._installer.Refused as refusal:
                self._call("failed", {"heading": refusal.heading, "body": refusal.body,
                                      "code": refusal.code})
            except Exception as error:                                # anything else, said plainly
                self._call("failed", {
                    "heading": "Something went wrong part way",
                    "body": (f"{error}\n\nRun this again to finish. Your register was not touched: "
                             f"it lives in {self._installer.register_dir()}, apart from the program."),
                    "code": "error"})
            finally:
                self._busy = False

        threading.Thread(target=body, name="herewise-setup", daemon=True).start()

    def _progress(self, step: str, done: int, total: int, detail: str) -> None:
        self._call("progress", {"step": step, "done": done, "total": total, "detail": detail})

    def _call(self, name: str, payload: dict) -> None:
        if self._window is not None:
            self._window.evaluate_js(f"window.hw && window.hw.{name}({json.dumps(payload)})")

    def _closing(self):
        # Closing mid-copy would leave half a program behind, so the window stays until it is done.
        return False if self._busy else None


def run(installer, uninstalling: bool) -> int:
    try:
        import webview
    except ImportError as error:
        raise NoWindow(str(error)) from error

    api = Api(installer, uninstalling)
    page = ui_dir() / "index.html"
    light = light_theme()
    window = webview.create_window(
        "Remove Herewise" if uninstalling else "Herewise Setup", str(page), js_api=api,
        width=WIDTH, height=HEIGHT, resizable=False, min_size=(WIDTH, HEIGHT),
        background_color="#F9F6F2" if light else "#15120F")     # --hw-paper, light and dark
    api._window = window
    window.events.closing += api._closing
    try:
        # gui="edgechromium" is WebView2, as in the app. private_mode keeps the page's storage in a
        # temporary folder that goes with it, so an installer leaves nothing of itself behind.
        webview.start(gui="edgechromium", http_server=True, private_mode=True)
    except Exception as error:                                     # pragma: no cover
        if not api._busy and api._installed_exe is None and not api._removed:
            raise NoWindow(str(error)) from error
        raise
    if api._removed:
        installer.remove_folder_after_exit()
    return 0
