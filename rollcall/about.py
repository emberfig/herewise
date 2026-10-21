"""What Herewise is made of, for the About screen (screen 40) and for the build.

The list lives here so the screen and the build cannot disagree. A PyInstaller build carries almost
no package metadata by default: the first one carried three packages' worth, and its About screen
would have listed pydantic alone, with pyzk, whose licence decides Herewise's own, silently gone.
packaging/herewise.spec copies the metadata of exactly these packages, and packaging/build.py
refuses to finish if any of it is missing from the built app.

Licences are read from the packages themselves, never from a written list, with one exception
recorded below and its source named.
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

PACKAGES = (
    ("fastapi", "the local web server this window talks to"),
    ("uvicorn", "runs it"),
    ("pydantic", "checks what every route is sent"),
    ("pyzk", "speaks the terminal's protocol"),
    ("reportlab", "draws the PDF exports"),
    ("openpyxl", "writes the Excel exports"),
    ("xlrd", "reads a roster saved as an old .xls"),
    ("python-multipart", "reads an uploaded roster"),
    ("pywebview", "draws the app's window"),
    ("pythonnet", "lets that window use the WebView2 control built into Windows"),
)

# Where a package's own metadata is unhelpful, the fact and where it came from. pyzk's metadata
# says only "LICENSE.txt"; the file itself is the GNU GPL version 2, read at the pinned commit
# (docs/RELEASE-READINESS.md, 2026-09-20). This is the one that decides Herewise's own licence, so
# it is never left as "stated in the package's own files".
KNOWN = {"pyzk": "GNU GPL version 2"}


def licence_of(name: str, meta) -> str:
    """Three places a package may state its licence, in the order they are trustworthy.

    Newer packaging puts an SPDX expression in License-Expression and leaves License empty; older
    packages put a filename or a sentence in License. FastAPI came back as "see the package" until
    License-Expression was read.
    """
    licence = (meta.get("License-Expression") or "").strip()
    if not licence:
        classifiers = [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
        if classifiers:
            licence = classifiers[0].split(" :: ")[-1].replace(" License", "")
    if not licence:
        stated = (meta.get("License") or "").strip()
        licence = stated if 0 < len(stated) <= 60 and not stated.lower().endswith(".txt") else ""
    return KNOWN.get(name) or licence or "stated in the package's own files"


def packages() -> list[dict]:
    """Every package on the list that this copy actually has. A source checkout without pywebview
    simply has no row for it; a built app always has them all, because the build checks."""
    rows = []
    for name, why in PACKAGES:
        try:
            meta = metadata.metadata(name)
        except metadata.PackageNotFoundError:
            continue
        rows.append({"name": name, "version": metadata.version(name),
                     "licence": licence_of(name, meta), "why": why})
    return rows


def reset_password_command() -> str:
    """How the only owner gets back in, on the computer holding the register.

    Screen 37 printed "python -m rollcall reset-password <username>" wherever it was running, and
    the people who will actually be locked out are running the installed app, which carries no
    Python and no source (Checklist Design, User management; 2026-09-21). An installed copy names
    its own executable, which is what Windows+R is given.
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" reset-password <username>'
    return "python -m rollcall reset-password <username>"
