"""The sole owner's reset, run as the installed app runs it: a windowed program opening its own console.

scripts/check_reset_console.py types into that console through the console API and reads its screen
back. It runs as a separate process because it detaches from its own console to do so. The launcher
is run with the base interpreter's pythonw, which, like the packaged Herewise.exe, starts with no
console at all. The same script run against dist/Herewise/Herewise.exe gave the same result on
2026-09-21.
"""
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYTHONW = Path(getattr(sys, "_base_executable", sys.executable)).with_name("pythonw.exe")

pytestmark = pytest.mark.skipif(os.name != "nt" or not PYTHONW.exists(),
                                reason="drives a Windows console")


def test_the_owner_reset_hides_the_password_and_lets_them_back_in():
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), sysconfig.get_path("purelib")]))
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_reset_console.py"),
                           str(PYTHONW), str(ROOT / "packaging" / "launch.py")],
                          capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert "error" not in result, result
    assert "New password:" in result["screen"] and "Type it again:" in result["screen"]
    assert result["password_on_screen"] is False             # typed, and never shown
    assert result["exit_code"] == 0
    assert result["new_password_signs_in"] and not result["old_password_signs_in"]
    assert result["audit"] == ["Set a new password for owner, reset from the command line on this computer"]
