"""The release signing rules in packaging/signing.py. The signing itself is proved by building with a
test certificate (docs/PROJECT-HANDOFF.md, Build a release); these hold the rules that decide what a
release is."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def signing(tmp_path):
    spec = importlib.util.spec_from_file_location("herewise_signing", ROOT / "packaging" / "signing.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["herewise_signing"] = module          # dataclasses look the module up by name
    spec.loader.exec_module(module)
    module.fake_signtool = tmp_path / "signtool.exe"
    module.fake_signtool.write_bytes(b"")
    return module


def test_nothing_configured_means_an_unsigned_build(signing):
    assert signing.configured({}) is None


def test_a_certificate_on_hardware_signs_with_sha256_and_a_timestamp(signing):
    signer = signing.configured({"HEREWISE_SIGN_THUMBPRINT": "ab cd ef 12",
                                 "HEREWISE_SIGNTOOL": str(signing.fake_signtool)})
    assert signer.for_release
    command = signing.sign_command(signer, Path("Herewise.exe"), "Herewise")
    assert command[1:3] == ["sign", "/fd"] and command[3] == "sha256"
    assert command[command.index("/sha1") + 1] == "ABCDEF12"
    assert command[command.index("/tr") + 1] == signing.DEFAULT_TIMESTAMP_URL
    assert command[command.index("/td") + 1] == "sha256"
    assert command[command.index("/du") + 1] == "https://emberfig.com/"
    assert "/f" not in command and "/p" not in command    # no key file, no password
    assert command[-1] == "Herewise.exe"


def test_a_file_certificate_or_no_timestamp_can_never_make_a_release(signing, tmp_path):
    pfx = signing.configured({"HEREWISE_SIGN_PFX": str(tmp_path / "t.pfx"),
                              "HEREWISE_SIGN_PFX_PASSWORD": "x",
                              "HEREWISE_SIGNTOOL": str(signing.fake_signtool)})
    assert not pfx.for_release
    untimed = signing.configured({"HEREWISE_SIGN_THUMBPRINT": "AB", "HEREWISE_TIMESTAMP": "0",
                                  "HEREWISE_SIGNTOOL": str(signing.fake_signtool)})
    assert not untimed.for_release
    assert "/tr" not in signing.sign_command(untimed, Path("x.exe"), "x")


def test_two_certificates_or_no_signtool_are_refused(signing, tmp_path):
    with pytest.raises(signing.SigningError, match="not both"):
        signing.configured({"HEREWISE_SIGN_THUMBPRINT": "AB", "HEREWISE_SIGN_PFX": "t.pfx",
                            "HEREWISE_SIGNTOOL": str(signing.fake_signtool)})
    with pytest.raises(signing.SigningError, match="signtool.exe was not found"):
        signing.configured({"HEREWISE_SIGN_THUMBPRINT": "AB",
                            "HEREWISE_SIGNTOOL": str(tmp_path / "missing" / "signtool.exe")})
