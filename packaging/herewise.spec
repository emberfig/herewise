# PyInstaller spec for Herewise. Built by packaging/build.py, which is where the reasoning is.
#
# One folder rather than one file. A one-file build unpacks itself into a temporary folder on every
# start, which on a budget laptop is several seconds each time and leaves the register's own start
# looking like a fault. A folder starts immediately and the files in it can be read.
#
# PyInstaller is GPL-2.0, but its bootloader carries an exception giving "unlimited permission to
# link or embed compiled bootloader and related files into combinations with other programs, and to
# distribute those combinations without any restriction" (its own COPYING.txt, read 2026-09-21).
# The runtime hooks it embeds (pyi_rth_inspect, pyi_rth_multiprocessing and pyi_rth_pkgutil in this
# build) are Apache-2.0, by the same file and by their own headers. So building with it imposes
# nothing on Herewise. pyzk still does, and that is the owner's question, not this file's.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, SPECPATH)
from PyInstaller.utils.hooks import copy_metadata    # noqa: E402
from rollcall import NAME, VERSION            # noqa: E402
from rollcall.about import PACKAGES           # noqa: E402
from version_resource import version_info     # noqa: E402

# Everything the app serves at runtime. The gallery is deliberately left out: it is a development
# page with its own fixtures and has no business in a lecturer's install.
# A file's destination is the folder it goes in, not the path it ends up at. Writing
# "rollcall/static/index.html" here made a *directory* called index.html with the file inside it,
# so the packaged app served every stylesheet and 404ed on its own front page. Only running the
# build found it.
STATIC = [
    (str(ROOT / "rollcall" / "static" / "index.html"), "rollcall/static"),
]
STATIC += [
    (str(ROOT / "rollcall" / "static" / folder), f"rollcall/static/{folder}")
    for folder in ("app", "components", "css", "fonts", "img")
]

# The installer reads this for the uninstall entry, so the version is never typed twice.
VERSION_FILE = Path(SPECPATH) / "VERSION"
VERSION_FILE.write_text(VERSION, encoding="utf-8")
STATIC.append((str(VERSION_FILE), "."))

# The About screen reads each package's version and licence from its metadata, and a build carries
# almost none by default: the first carried click, pydantic and websockets, so the screen would have
# listed pydantic alone. These are the packages it names (rollcall/about.py), each with its own
# licence files, which travel inside the dist-info folders.
for package, _ in PACKAGES:
    STATIC += copy_metadata(package)

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=STATIC,
    hiddenimports=[
        # Uvicorn picks these up by name at runtime, so the analysis cannot see them.
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
        # pywebview chooses its backend at runtime; this build only ever wants WebView2.
        "webview.platforms.edgechromium",
    ],
    excludes=[
        # None of these is used, and each one costs tens of megabytes on a 300 MB budget.
        # PIL is NOT in this list and must never be put back: reportlab does `from PIL import
        # Image` at the top of reportlab/lib/utils.py, unconditionally, so excluding it made every
        # PDF export in the packaged build fail with ModuleNotFoundError while every PDF export in
        # a source run worked. A lecturer hit it on Export PDF and saw "Internal Server Error"
        # (2026-09-22). scripts/check_exports.mjs asks the packaged app for every export and is
        # what now stands between that exclusion and a release.
        "tkinter", "matplotlib", "numpy", "pandas", "pytest", "playwright",
        "webview.platforms.cef", "webview.platforms.qt", "webview.platforms.gtk",
        "webview.platforms.android", "webview.platforms.cocoa",
        # setuptools is a build-time tool, and pulling it in makes PyInstaller add a runtime hook
        # for pkg_resources whose vendored code imports a `backports` package that is not there.
        # The first build died on that before reaching a single line of Herewise.
        "setuptools", "pkg_resources", "_distutils_hack",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Herewise",
    icon=str(ROOT / "rollcall" / "static" / "img" / "herewise.ico"),
    console=False,          # no terminal window: that is the whole point of packaging this
    version=version_info(NAME, VERSION, f"{NAME}, lecture attendance from a fingerprint terminal",
                         f"{NAME}.exe"),
    debug=False,
    strip=False,
    upx=False,              # UPX-packed executables are what antivirus heuristics flag first
)

COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Herewise",
)
