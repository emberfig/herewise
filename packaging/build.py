"""Build Herewise into something a lecturer can install.

    python packaging/build.py            the app folder and the installer
    python packaging/build.py --app      the app folder only, for a quick check
    python packaging/build.py --release  the same, and refuses to finish unless both executables
                                         are signed, timestamped and verify (packaging/signing.py)

In steps, for a build signed elsewhere (.github/workflows/release.yml, where SignPath signs each
executable between steps):

    python packaging/build.py --app        the app folder; Herewise.exe is then signed
    python packaging/build.py --installer  the installer from the app folder already in dist/,
                                           never rebuilt, so it carries the signed Herewise.exe
    python packaging/build.py --finish     the changelog, the source archive and the checksums,
                                           last, because signing changes the bytes they check

Signing happens whenever a certificate is configured (packaging/signing.py says how): the app's
Herewise.exe before it is packed into the installer, then the installer, then the checksums.

It produces, in dist/:

    Herewise/                 the app folder: Herewise.exe and everything it needs
    Herewise-Setup-<v>.exe    a per-user installer that needs no administrator rights
    Herewise-<v>-source.zip   the source of exactly this build (GPL), cut from a clean commit
    SHA256SUMS.txt            the checksum of every file anyone is asked to run or read
    CHANGELOG.md              copied from the repo, so the release carries its own history

Why a folder and not one file: a one-file build unpacks itself into a temporary folder on every
start, which on a budget laptop takes several seconds and makes the register's own start look like
a fault. A folder starts at once, and its files can be read by whoever is asked to trust them.

Why our own installer rather than Inno Setup or MSI: both want administrator rights by default,
and an MSI without them is awkward. Everything Herewise needs lives in one per-user folder, so the
installer is a small program that copies a folder, makes two shortcuts and writes one uninstall
entry under HKCU. It is built with the same PyInstaller, and its behaviour is in
packaging/installer.py where anyone can read it.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rollcall import NAME, VERSION            # noqa: E402

import signing                                # noqa: E402  (packaging/signing.py, beside this file)

DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP = DIST / NAME
INSTALLER_NAME = f"{NAME}-Setup-{VERSION}"


def run(*args: str) -> None:
    print("  " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode:
        raise SystemExit(f"{args[0]} failed with {result.returncode}")


def pyinstaller(spec: str, *extra: str) -> None:
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(BUILD), *extra, str(ROOT / "packaging" / spec))


def build_app() -> None:
    print(f"Building {NAME} {VERSION}")
    if APP.exists():
        shutil.rmtree(APP)
    pyinstaller("herewise.spec")
    if not (APP / f"{NAME}.exe").exists():
        raise SystemExit("PyInstaller finished but produced no executable")
    missing = missing_metadata(APP)
    if missing:
        # A missing row on the About screen is silent, so it is caught here instead.
        raise SystemExit("the built app has no metadata for " + ", ".join(missing)
                         + ", so its About screen would leave them out")
    # The licences of everything inside travel with it, because the About screen names them and
    # somebody may want to read them without opening the app.
    licences = APP / "licences"
    licences.mkdir(exist_ok=True)
    for name in ("Inter-OFL.txt", "InstrumentSerif-OFL.txt"):
        shutil.copy2(ROOT / "rollcall" / "static" / "fonts" / name, licences / name)
    # Herewise's own licence, both versions: it is GPL-2.0-or-later and the build goes out under
    # version 3, because the Apache-2.0 parts below are compatible with version 3 only.
    shutil.copy2(ROOT / "LICENSE", licences / "GPL-2.0.txt")
    shutil.copy2(ROOT / "GPL-3.0.txt", licences / "GPL-3.0.txt")
    # OpenSSL 3 ships inside Python's ssl module and inside cryptography, with no dist-info of its
    # own, so the Apache License travels here as well. cryptography's copy is the full text.
    apache = next(APP.glob("_internal/cryptography-*.dist-info/licenses/LICENSE.APACHE"), None)
    if apache is None:
        raise SystemExit("no Apache License text found in the build, so OpenSSL's licence would not travel")
    shutil.copy2(apache, licences / "Apache-2.0.txt")
    # pywebview brings Microsoft's WebView2 SDK files as binaries under a BSD licence whose notice
    # must travel with them. pywebview's own licence does not carry it, so it travels from here.
    if not any(APP.glob("_internal/webview/lib/**/*WebView2*.dll")):
        raise SystemExit("no WebView2 SDK files in the build, so the window could not open")
    shutil.copy2(ROOT / "packaging" / "licences" / "WebView2-SDK-BSD.txt", licences / "WebView2-SDK-BSD.txt")
    (licences / "README.txt").write_text(
        f"{NAME} {VERSION}\n\n"
        "Herewise is free software: you can redistribute it and/or modify it under the terms of the\n"
        "GNU General Public License as published by the Free Software Foundation, either version 2\n"
        "of the License, or (at your option) any later version. This build is distributed under\n"
        "version 3 (GPL-3.0.txt). It comes with no warranty. Copyright (C) 2026 Emberfig.\n"
        "The source of this release is published beside its installer.\n\n"
        "The typefaces here are under the SIL Open Font License 1.1.\n"
        "OpenSSL 3, inside Python's ssl module and inside cryptography, is under the Apache\n"
        "License 2.0 (Apache-2.0.txt).\n"
        "Microsoft's WebView2 SDK files, which draw the window, are under the BSD-style licence\n"
        "in WebView2-SDK-BSD.txt.\n"
        "The libraries Herewise names on its About screen are listed there with their licences,\n"
        "read from the packages themselves rather than from a written list. Each package's own\n"
        "licence files are in its .dist-info folder under _internal.\n", encoding="utf-8")
    print(f"  app folder: {APP} ({folder_size(APP) / 1_000_000:.0f} MB)")


def missing_metadata(app: Path) -> list[str]:
    """The packages the About screen names whose metadata is not in the built app."""
    from rollcall.about import PACKAGES

    def normal(name: str) -> str:
        return re.sub(r"[-_.]+", "_", name).lower()

    present = {normal(folder.name[:-len(".dist-info")].rsplit("-", 1)[0])
               for folder in (app / "_internal").glob("*.dist-info")}
    return [name for name, _ in PACKAGES if normal(name) not in present]


def build_installer() -> None:
    print("Building the installer")
    payload = ROOT / "packaging" / "payload"
    if payload.exists():
        shutil.rmtree(payload)
    # The installer carries the app folder inside itself as data, so one file is all anyone needs,
    # and its own window's page with the app's tokens and fonts beside it.
    shutil.copytree(APP, payload / NAME)
    import installer_window                    # packaging/installer_window.py, beside this file
    installer_window.stage_ui(payload / "installer_ui", ROOT)
    if (payload / "installer_ui" / "preview.js").exists():
        raise SystemExit("preview.js was staged into the installer; it is for looking at screens only")
    try:
        pyinstaller("installer.spec")
    finally:
        shutil.rmtree(payload, ignore_errors=True)
    made = DIST / f"{INSTALLER_NAME}.exe"
    if not made.exists():
        raise SystemExit("the installer did not build")
    print(f"  installer: {made} ({made.stat().st_size / 1_000_000:.0f} MB)")


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def source_archive() -> Path | None:
    """The source of exactly this build, which the GPL asks to travel beside the installer.

    Cut from the commit being built, so it can only be the source if nothing is uncommitted. A build
    from a dirty tree gets no archive and says it must not be handed out.
    """
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.strip()
    if dirty:
        print("  NO SOURCE ARCHIVE: the working tree has uncommitted changes, so no archive can be "
              "this build's source. Commit, then build again before handing it to anyone.")
        return None
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    target = DIST / f"{NAME}-{VERSION}-source.zip"
    run("git", "-C", str(ROOT), "archive", "--format=zip", f"--prefix={NAME.lower()}-{VERSION}/",
        "-o", str(target), "HEAD")
    print(f"  source: {target} (commit {commit}, {target.stat().st_size / 1_000_000:.1f} MB)")
    return target


def checksums() -> None:
    """One checksum for every file anyone is asked to run or read, so a download can be verified."""
    lines = []
    for path in sorted(DIST.glob("*.exe")) + sorted(DIST.glob(f"{NAME}-*-source.zip")):
        lines.append(f"{sha256(path)}  {path.name}")
    app_exe = APP / f"{NAME}.exe"
    if app_exe.exists():
        lines.append(f"{sha256(app_exe)}  {NAME}/{NAME}.exe")
    target = DIST / "SHA256SUMS.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  checksums: {target}")
    for line in lines:
        print(f"    {line}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finish(require_source: bool) -> None:
    """The changelog, the source archive and the checksums: last, since signing changes the bytes."""
    installer = DIST / f"{INSTALLER_NAME}.exe"
    if not installer.exists():
        raise SystemExit(f"nothing to finish: {installer.name} has not been built")
    shutil.copy2(ROOT / "CHANGELOG.md", DIST / "CHANGELOG.md")
    if source_archive() is None and require_source:
        raise SystemExit("A release carries its source, and this tree has uncommitted changes.")
    checksums()


def sign_file(signer: signing.Signer | None, path: Path, description: str, release: bool) -> None:
    if signer is None:
        print(f"  NOT SIGNED: {path.name}. Windows will warn anyone who runs it. Fine for a test "
              "build; a release uses --release.")
        return
    signing.sign(signer, path, description)
    seen = signing.verify(signer, path, release)
    print(f"  signed: {path.name} by {seen['subject']}"
          + (", timestamped" if seen["timestamped"] else ", NOT timestamped (test only)"))


def main() -> None:
    if os.name != "nt":
        raise SystemExit("Herewise is a Windows program, so it is built on Windows.")
    if "--installer" in sys.argv:
        if not (APP / f"{NAME}.exe").exists():
            raise SystemExit(f"--installer packs the app folder already built, and {APP} has no {NAME}.exe")
        build_installer()
        print("Done.")
        return
    if "--finish" in sys.argv:
        finish(require_source=True)
        print("Done.")
        return
    only_app = "--app" in sys.argv
    release = "--release" in sys.argv
    try:
        signer = signing.configured()
    except signing.SigningError as error:
        raise SystemExit(str(error)) from error
    if release and (signer is None or not signer.for_release):
        raise SystemExit("A release is signed with Emberfig's certificate on its token or cloud HSM, "
                         "and timestamped. Set HEREWISE_SIGN_THUMBPRINT and leave timestamping on "
                         "(docs/PROJECT-HANDOFF.md, Build a release). Nothing was built.")
    DIST.mkdir(exist_ok=True)
    try:
        build_app()
        # Signed before it is packed, so the copy the installer puts on a lecturer's machine is too.
        sign_file(signer, APP / f"{NAME}.exe", NAME, release)
        if not only_app:
            build_installer()
            sign_file(signer, DIST / f"{INSTALLER_NAME}.exe", f"{NAME} installer", release)
            finish(require_source=release)
    except signing.SigningError as error:
        raise SystemExit(f"Signing failed, so this build must not be handed to anyone: {error}") from error
    print("Done.")


if __name__ == "__main__":
    main()
