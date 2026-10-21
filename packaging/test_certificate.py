"""Make a throwaway code signing certificate, to test the signing pipeline without a real one.

    python packaging/test_certificate.py

It writes a self-signed certificate and its key to a .pfx in the system temporary folder, never in
the repo, and prints the environment variables that make `packaging/build.py` sign with it. Windows
does not trust it, so a file signed with it shows "unknown publisher" exactly as an unsigned one
does; what it proves is that the build signs the right files in the right order and that the signed
installer still runs. It touches no certificate store.

The subject says what it is, so a file signed with it can never be mistaken for a release.
"""
from __future__ import annotations

import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SUBJECT = "Emberfig TEST ONLY, not a release certificate"


def make(folder: Path) -> tuple[Path, str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SUBJECT)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, key_cert_sign=False, crl_sign=False,
                                     encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .sign(key, hashes.SHA256())
    )
    password = secrets.token_urlsafe(18)
    blob = pkcs12.serialize_key_and_certificates(b"herewise-test", key, certificate, None,
                                                 BestAvailableEncryption(password.encode()))
    path = folder / "herewise-test-signing.pfx"
    path.write_bytes(blob)
    return path, password, certificate.fingerprint(hashes.SHA1()).hex().upper()


if __name__ == "__main__":
    place = Path(tempfile.gettempdir()) / "herewise-test-signing"
    place.mkdir(exist_ok=True)
    pfx, password, thumbprint = make(place)
    print(f"Test certificate: {pfx}  (SHA-1 {thumbprint}, valid 7 days, trusted by nothing)")
    print("To build with it, offline:")
    print(f'  $env:HEREWISE_SIGN_PFX = "{pfx}"')
    print(f'  $env:HEREWISE_SIGN_PFX_PASSWORD = "{password}"')
    print('  $env:HEREWISE_TIMESTAMP = "0"')
