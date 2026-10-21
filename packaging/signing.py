"""Code signing for the release: which certificate, what is signed, in what order, and the check.

Decided 2026-09-21, inside the owner's earlier decision to buy a standard (OV) certificate rather
than an EV one (docs/DECISIONS-AND-LESSONS.md, 2026-09-20 and 2026-09-21):

- **Issued to the organisation, Emberfig.** An organisation-validated certificate names the
  registered organisation as the publisher Windows shows. A certificate issued to an individual
  would put a founder's legal name on every install prompt, which the studio never allows.
- **The key never exists as a file.** Since June 2023 a publicly trusted code signing key must be
  generated and kept on hardware: a USB token, or a cloud signing service's HSM. Either presents
  the certificate through Windows' certificate store, so the build names it by its SHA-1
  thumbprint, `HEREWISE_SIGN_THUMBPRINT`, and the token or service asks for its own PIN. Nothing
  secret is ever in the repo, in an environment file, or in this script.
- **Everything is timestamped (RFC 3161, SHA-256)**, so a signature stays valid after the
  certificate expires, which now happens every year.
- **The order is fixed:** the app's Herewise.exe is signed before it is packed into the installer,
  so the installed program carries the signature too; then the installer is signed; then both are
  verified; then the checksums are taken, because signing changes the bytes.
- **A release cannot go out unsigned by accident.** `build.py --release` stops unless both files
  are signed, timestamped and verify against Windows' trusted roots.

A certificate in a .pfx file (`HEREWISE_SIGN_PFX` and `HEREWISE_SIGN_PFX_PASSWORD`) is accepted for
one purpose only: testing this pipeline with a throwaway certificate made by
`packaging/test_certificate.py`. No publicly trusted certificate can be issued that way any more.

signtool.exe comes from Microsoft's Windows SDK build tools. `HEREWISE_SIGNTOOL` names it; otherwise
it is looked for in %USERPROFILE%\\herewise-build-tools, on the PATH, and in the Windows Kits folder.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"
PUBLISHER_URL = "https://emberfig.com/"


class SigningError(Exception):
    pass


@dataclass(frozen=True)
class Signer:
    signtool: Path
    thumbprint: str | None = None
    pfx: Path | None = None
    pfx_password: str | None = None
    timestamp_url: str | None = DEFAULT_TIMESTAMP_URL

    @property
    def for_release(self) -> bool:
        """Only a certificate held on hardware can be a release certificate."""
        return self.thumbprint is not None and self.timestamp_url is not None


def find_signtool(env: dict) -> Path | None:
    named = env.get("HEREWISE_SIGNTOOL")
    if named:
        return Path(named)
    home = Path(env.get("USERPROFILE", str(Path.home())))
    for candidate in sorted((home / "herewise-build-tools").glob("sdk-*-x64/signtool.exe"), reverse=True):
        return candidate
    on_path = shutil.which("signtool")
    if on_path:
        return Path(on_path)
    kits = Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
    for candidate in sorted(kits.glob("*/x64/signtool.exe"), reverse=True):
        return candidate
    return None


def configured(env: dict | None = None) -> Signer | None:
    """The signer the environment describes, or None when nothing is set up to sign."""
    env = dict(os.environ if env is None else env)
    thumbprint = (env.get("HEREWISE_SIGN_THUMBPRINT") or "").replace(" ", "").upper() or None
    pfx = env.get("HEREWISE_SIGN_PFX") or None
    if not thumbprint and not pfx:
        return None
    if thumbprint and pfx:
        raise SigningError("Set HEREWISE_SIGN_THUMBPRINT or HEREWISE_SIGN_PFX, not both.")
    signtool = find_signtool(env)
    if signtool is None or not signtool.exists():
        raise SigningError("signtool.exe was not found. Install the Windows SDK signing tools, or "
                           "set HEREWISE_SIGNTOOL to its path.")
    stamp = env.get("HEREWISE_TIMESTAMP_URL", DEFAULT_TIMESTAMP_URL)
    if env.get("HEREWISE_TIMESTAMP") == "0":
        stamp = None                                  # testing offline only; a release refuses it
    return Signer(signtool=signtool, thumbprint=thumbprint, pfx=Path(pfx) if pfx else None,
                  pfx_password=env.get("HEREWISE_SIGN_PFX_PASSWORD"), timestamp_url=stamp)


def sign_command(signer: Signer, path: Path, description: str) -> list[str]:
    command = [str(signer.signtool), "sign", "/fd", "sha256", "/d", description, "/du", PUBLISHER_URL]
    if signer.thumbprint:
        command += ["/sha1", signer.thumbprint]
    else:
        command += ["/f", str(signer.pfx)]
        if signer.pfx_password:
            command += ["/p", signer.pfx_password]
    if signer.timestamp_url:
        command += ["/tr", signer.timestamp_url, "/td", "sha256"]
    return command + [str(path)]


def sign(signer: Signer, path: Path, description: str) -> None:
    result = subprocess.run(sign_command(signer, path, description), capture_output=True, text=True)
    if result.returncode:
        # The password is in the command for a test certificate, so only signtool's own words are shown.
        raise SigningError(f"signtool could not sign {path.name}: "
                           f"{(result.stdout + result.stderr).strip()[-600:]}")


def inspect(path: Path) -> dict:
    """What Windows itself reads from the file's signature, through PowerShell's own cmdlet."""
    script = ("$s = Get-AuthenticodeSignature -LiteralPath $env:HW_FILE; "
              "[pscustomobject]@{ status = [string]$s.Status; "
              "subject = if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { $null }; "
              "thumbprint = if ($s.SignerCertificate) { $s.SignerCertificate.Thumbprint } else { $null }; "
              "timestamped = [bool]$s.TimeStamperCertificate } | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, env={**os.environ, "HW_FILE": str(path)})
    if result.returncode:
        raise SigningError(f"could not read the signature on {path.name}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def verify(signer: Signer, path: Path, release: bool) -> dict:
    """A release signature must be Valid against Windows' trusted roots and timestamped. A test
    certificate is untrusted by design, so for it the check is that the file carries that very
    certificate's signature."""
    seen = inspect(path)
    if release:
        if seen["status"] != "Valid" or not seen["timestamped"]:
            raise SigningError(f"{path.name} does not carry a valid, timestamped signature: {seen}")
        return seen
    expected = signer.thumbprint or _pfx_thumbprint(signer)
    if not seen["thumbprint"] or (expected and seen["thumbprint"].upper() != expected.upper()):
        raise SigningError(f"{path.name} is not signed with the configured certificate: {seen}")
    return seen


def _pfx_thumbprint(signer: Signer) -> str | None:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.serialization import pkcs12
    except ImportError:
        return None
    password = signer.pfx_password.encode() if signer.pfx_password else None
    _, certificate, _ = pkcs12.load_key_and_certificates(signer.pfx.read_bytes(), password)
    return certificate.fingerprint(hashes.SHA1()).hex().upper()
