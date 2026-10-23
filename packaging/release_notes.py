"""Write the notes for a GitHub release from CHANGELOG.md.

    python packaging/release_notes.py dist/release-notes.md

The notes are the version's own entry in CHANGELOG.md, then how to check the download and what
SmartScreen will say, then where the source is. A release that changes the register's schema also
needs a paragraph on upgrading; add it to the draft before publishing, as 0.1.18's notes did.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rollcall import NAME, VERSION            # noqa: E402


def entry(changelog: str, version: str) -> str:
    """The body of the '## <version>' section, without its heading."""
    match = re.search(rf"^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    if match is None or not match.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no entry for {version}, so the release has nothing to say")
    return match.group(1).strip()


def notes(changelog: str, version: str, signed: bool) -> str:
    installer = f"{NAME}-Setup-{version}.exe"
    if signed:
        smartscreen = ("The installer is per user and needs no administrator rights. It is code signed: "
                       "Windows names SignPath Foundation as the publisher, which signs it for "
                       "Emberfig (see the code signing policy in the README).")
    else:
        smartscreen = ("The installer is per user and needs no administrator rights. It is not yet code "
                       "signed, so Windows SmartScreen will warn first: choose More info, then Run "
                       "anyway, once the checksum matches.")
    return (
        f"{NAME} {version}.\n\n"
        "**What's in it**\n\n"
        f"{entry(changelog, version)}\n\n"
        "**Install**\n\n"
        f"Download `{installer}` and check it before running it:\n\n"
        "```powershell\n"
        f"Get-FileHash .\\{installer} -Algorithm SHA256\n"
        "```\n\n"
        f"It should match the line in `SHA256SUMS.txt`. {smartscreen}\n\n"
        "Needs Windows 10 or 11, 64-bit, and a ZKTeco K40 on a direct Ethernet cable.\n\n"
        "**Source**\n\n"
        f"`{NAME}-{version}-source.zip` is the source of exactly this installer, the same files as "
        f"this repository at `v{version}`. {NAME} is free software under the GNU GPL, version 2 or "
        "any later version; this release is distributed under version 3.\n"
    )


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python packaging/release_notes.py <output.md> [--signed]")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    Path(sys.argv[1]).write_text(notes(changelog, VERSION, "--signed" in sys.argv), encoding="utf-8")
    print(f"  release notes: {sys.argv[1]}")


if __name__ == "__main__":
    main()
