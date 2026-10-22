"""Light or dark: System, Light or Dark, chosen on this computer.

Asked for on 2026-10-22. Until then Herewise only followed Windows, through prefers-color-scheme.

Kept in a file in the data folder beside the register rather than in the register. The register is
what moves when someone downloads their data or restores a backup, and how the screen looks is this
computer's business: a lecturer who works in the dark at home should not hand the department's
laptop a dark screen along with the attendance. Not in the window's own storage either, because
that belongs to the page's origin, and the port the app listens on is the first free one from 8000
(config.free_port), so a choice kept there is forgotten whenever another program holds 8000.

Applied before the first paint by a script the page loads in its head, before any stylesheet
(``/api/appearance.js``), so there is never a light frame before a dark screen. The packaged
window's own background, which shows for a moment before the page has painted anything, is set to
the same paper (``window_background``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CHOICES = ("system", "light", "dark")
DEFAULT = "system"
FILE = "appearance.json"

_TOKENS = Path(__file__).resolve().parent / "static" / "css" / "tokens.css"


class AppearanceError(ValueError):
    pass


def read(folder: Path) -> str:
    """The choice saved on this computer, or System when there is none or it cannot be read."""
    try:
        value = json.loads((Path(folder) / FILE).read_text(encoding="utf-8")).get("theme")
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return value if value in CHOICES else DEFAULT


def write(folder: Path, theme: str) -> str:
    if theme not in CHOICES:
        raise AppearanceError("Choose System, Light or Dark.")
    path = Path(folder) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside and moved into place, so a crash halfway leaves the old choice, not half a file.
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps({"theme": theme}), encoding="utf-8")
    partial.replace(path)
    return theme


def script(theme: str) -> str:
    """The script the page runs before it paints. System sets nothing, which leaves the tokens'
    own prefers-color-scheme rule to follow Windows, as Herewise always did."""
    theme = theme if theme in CHOICES else DEFAULT
    return ("// How Herewise looks on this computer, set before the page paints (rollcall/appearance.py).\n"
            f'document.documentElement.dataset.appearance = "{theme}";\n'
            + (f'document.documentElement.dataset.theme = "{theme}";\n' if theme != "system" else ""))


def paper(tokens: Path = _TOKENS) -> dict[str, str]:
    """The page's background in each theme, read from the generated tokens so it cannot drift."""
    text = tokens.read_text(encoding="utf-8")
    light = re.search(r":root\s*\{[^}]*--hw-paper:\s*(#[0-9A-Fa-f]{6})", text)
    dark = re.search(r':root\[data-theme="dark"\][^{]*\{[^}]*--hw-paper:\s*(#[0-9A-Fa-f]{6})', text)
    return {"light": light.group(1) if light else "#F9F6F2", "dark": dark.group(1) if dark else "#15120F"}


def windows_prefers_dark() -> bool:
    """Whether Windows is set to dark mode for apps. False whenever it cannot be read."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


def window_background(theme: str, prefers_dark=windows_prefers_dark) -> str:
    """The colour the packaged window shows before the page paints: the paper of the theme the page
    is about to draw, so opening Herewise in the dark does not flash white."""
    dark = theme == "dark" or (theme not in ("light", "dark") and prefers_dark())
    return paper()["dark" if dark else "light"]
