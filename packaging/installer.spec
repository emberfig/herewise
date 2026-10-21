# PyInstaller spec for the Herewise installer. Built by packaging/build.py.
#
# One file, unlike the app itself: an installer is downloaded, run once and thrown away, so the
# few seconds it spends unpacking itself cost nothing and one file is what people expect to be
# given. It carries the whole app folder inside it as data, and its own window: the page in
# packaging/installer_ui, staged with the app's tokens and fonts by build.py, drawn by pywebview's
# WebView2 backend exactly as the app is (packaging/installer_window.py).

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, SPECPATH)
from rollcall import NAME, VERSION            # noqa: E402
from version_resource import version_info     # noqa: E402

a = Analysis(
    [str(ROOT / "packaging" / "installer.py")],
    pathex=[str(ROOT), str(ROOT / "packaging")],
    binaries=[],
    datas=[(str(ROOT / "packaging" / "payload" / NAME), NAME),
           (str(ROOT / "packaging" / "payload" / "installer_ui"), "installer_ui")],
    hiddenimports=["installer_window", "webview.platforms.edgechromium"],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest", "fastapi", "uvicorn",
              "reportlab", "openpyxl", "pydantic",
              "webview.platforms.cef", "webview.platforms.qt", "webview.platforms.gtk",
              "webview.platforms.android", "webview.platforms.cocoa",
              "setuptools", "pkg_resources", "_distutils_hack"],
    noarchive=False,
)
pyz = PYZ(a.pure)

EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"{NAME}-Setup-{VERSION}",
    icon=str(ROOT / "rollcall" / "static" / "img" / "herewise.ico"),
    version=version_info(NAME, VERSION, f"{NAME} installer, per user, no administrator rights",
                         f"{NAME}-Setup-{VERSION}.exe"),
    # Windowed: an installer double-clicked from Downloads must not flash a console. The --quiet
    # mode still works, and its output goes wherever the caller redirects it.
    console=False,
    debug=False,
    strip=False,
    upx=False,
    # An installer that writes only to the user's own folders asks for nothing more than that.
    uac_admin=False,
)
