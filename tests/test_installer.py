"""The installer: it replaces the program, and it never deletes a register.

packaging/installer.py is not part of the rollcall package, so it is loaded from its path. Nothing
here writes to the real registry or makes real shortcuts: both are replaced with recorders, and
every folder is under tmp_path.
"""
import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def installer(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("herewise_installer",
                                                  ROOT / "packaging" / "installer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / name))
    monkeypatch.setattr(sys, "argv", ["Herewise-Setup.exe", "--quiet"])

    module.calls = []
    monkeypatch.setattr(module, "write_uninstall_entry",
                        lambda folder, version, size: module.calls.append(("entry", version)))
    monkeypatch.setattr(module, "installed_version", lambda: "0.1.9")
    monkeypatch.setattr(module, "remove_uninstall_entry",
                        lambda: module.calls.append(("remove entry",)))
    monkeypatch.setattr(module, "make_shortcut",
                        lambda link, target, icon: module.calls.append(("shortcut", link.name)) or True)
    monkeypatch.setattr(module.subprocess, "Popen",
                        lambda *a, **k: module.calls.append(("delete folder later",)))
    # This machine's own WebView2 must not decide a test: present unless a test says otherwise.
    module.runtime = "153.0.3000.0"
    monkeypatch.setattr(module, "webview2_version", lambda: module.runtime)
    monkeypatch.setattr(module, "beside_installer", lambda: tmp_path / "usb")
    # Nor may a Herewise open on this machine: nothing is running unless a test says it is.
    monkeypatch.setattr(module, "running_copies", lambda: [])
    # No test may put a real message box on the screen. One did, on 2026-09-23: a test without
    # --quiet fell through to the boxes and an "Install Herewise?" sat on the desktop for two
    # minutes. What would have been shown is recorded instead.
    module.shown = []
    monkeypatch.setattr(module, "ask", lambda heading, body: module.shown.append(heading) or True)
    monkeypatch.setattr(module, "say",
                        lambda heading, body, start=None: module.shown.append(heading) or 0)

    # What the installer carries: an app folder the way a one-folder build lays it out.
    payload = tmp_path / "payload" / "Herewise"
    (payload / "_internal").mkdir(parents=True)
    (payload / "_internal" / "VERSION").write_text("0.2.0", encoding="utf-8")
    (payload / "Herewise.exe").write_bytes(b"new program")
    monkeypatch.setattr(module, "bundled", lambda: payload)
    return module


def test_the_version_is_read_from_where_a_one_folder_build_puts_it(installer, tmp_path):
    folder = tmp_path / "app"
    (folder / "_internal").mkdir(parents=True)
    assert installer.version_of(folder) == "0.0.0"
    (folder / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    assert installer.version_of(folder) == "0.1.0"
    (folder / "_internal" / "VERSION").write_text("0.1.1", encoding="utf-8")
    assert installer.version_of(folder) == "0.1.1"             # where PyInstaller 6 actually puts it


def test_an_upgrade_replaces_the_program_and_writes_one_entry(installer):
    target = installer.program_dir()
    target.mkdir(parents=True)
    (target / "left over from 0.1.0.txt").write_text("old", encoding="utf-8")

    assert installer.install(with_desktop=False) == 0
    assert not (target / "left over from 0.1.0.txt").exists()
    assert (target / "Herewise.exe").read_bytes() == b"new program"
    assert (target / "uninstall.exe").exists()
    assert not target.with_name("Herewise.old").exists()
    assert installer.calls == [("shortcut", "Herewise.lnk"), ("entry", "0.2.0")]
    assert not installer.register_dir().exists()               # the register folder is never made


def test_a_running_copy_stops_the_upgrade_before_anything_is_deleted(installer):
    # Windows refuses to rename a folder while a file in it is open, which is what a running
    # Herewise.exe does to its own folder (checked against the built app on 2026-09-21).
    target = installer.program_dir()
    (target / "_internal").mkdir(parents=True)
    (target / "Herewise.exe").write_bytes(b"old program")
    with (target / "_internal" / "python311.dll").open("w") as held:
        held.write("in use")
        assert installer.install(with_desktop=False) == 1
    assert (target / "Herewise.exe").read_bytes() == b"old program"
    assert (target / "_internal" / "python311.dll").exists()
    assert installer.calls == []


def test_an_upgrade_never_deletes_a_register_kept_in_the_program_folder(installer):
    target = installer.program_dir()
    target.mkdir(parents=True)
    (target / "portable").write_text("", encoding="utf-8")
    (target / "rollcall.db").write_bytes(b"a term of scans")

    assert installer.install(with_desktop=False) == 1
    assert (target / "rollcall.db").read_bytes() == b"a term of scans"
    assert not (target / "Herewise.exe").exists()              # nothing was copied over it either
    assert installer.calls == []


def test_removing_never_deletes_a_register_kept_in_the_program_folder(installer):
    target = installer.program_dir()
    target.mkdir(parents=True)
    (target / "rollcall.db").write_bytes(b"a term of scans")

    assert installer.uninstall() == 1
    assert (target / "rollcall.db").read_bytes() == b"a term of scans"
    assert installer.calls == []                                # entry kept, folder not scheduled


def test_webview2_already_there_is_left_alone(installer, monkeypatch):
    ran = []
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: ran.append(a))
    assert installer.ensure_webview2() == ""
    assert ran == []


def test_missing_webview2_is_installed_per_user_from_the_file_beside_the_installer(installer, monkeypatch):
    installer.runtime = None
    usb = installer.beside_installer()
    usb.mkdir()
    (usb / installer.WEBVIEW2_OFFLINE).write_bytes(b"microsoft's installer")
    ran = []

    def run(command, **kwargs):
        ran.append(command)
        installer.runtime = "153.0.3000.0"             # what the real one leaves behind
    monkeypatch.setattr(installer.subprocess, "run", run)

    said = installer.ensure_webview2()
    assert ran == [[str(usb / installer.WEBVIEW2_OFFLINE), "/silent", "/install"]]
    assert "was installed from the file beside this installer" in said


def test_missing_webview2_with_nothing_beside_still_installs_herewise_and_says_what_to_do(installer):
    installer.runtime = None
    assert installer.install(with_desktop=False) == 0
    said = installer.ensure_webview2()
    assert "will open in your web browser instead" in said
    assert installer.WEBVIEW2_OFFLINE in said
    assert (installer.program_dir() / "Herewise.exe").exists()


def test_removing_while_herewise_is_open_changes_nothing(installer, monkeypatch):
    # On 2026-09-24 a quiet removal ran against an open Herewise: the entry and the shortcuts went,
    # the program folder stayed locked, and Windows no longer listed anything to remove it with.
    target = installer.program_dir()
    target.mkdir(parents=True)
    (target / "Herewise.exe").write_bytes(b"running")
    monkeypatch.setattr(installer, "running_copies", lambda: [4242])

    assert installer.uninstall() == 1
    assert installer.calls == []                                # entry kept, folder not scheduled
    assert (target / "Herewise.exe").read_bytes() == b"running"


def test_removing_takes_the_program_and_leaves_the_register(installer):
    target = installer.program_dir()
    target.mkdir(parents=True)
    register = installer.register_dir()
    register.mkdir(parents=True)
    (register / "rollcall.db").write_bytes(b"a term of scans")

    assert installer.uninstall() == 0
    assert installer.calls == [("remove entry",), ("delete folder later",)]
    assert (register / "rollcall.db").read_bytes() == b"a term of scans"


# -- the installer's own window (asked for on 2026-09-23) -------------------------------------------

def test_progress_is_reported_in_order_and_ends_at_the_total(installer):
    seen = []
    done = installer.do_install(True, lambda step, at, total, detail: seen.append((step, at, total)))
    steps = [s for s, _, _ in seen]
    assert steps[0] == "prepare" and steps[-1] == "done"
    order = ["prepare", "copy", "shortcuts", "entry", "runtime", "done"]
    assert [s for s in order if s in steps] == order, steps
    assert seen[-1][1] == seen[-1][2], "the bar ends full"
    assert all(a[1] <= b[1] for a, b in zip(seen, seen[1:])), "and never goes backwards"
    assert done["version"] == "0.2.0" and done["replacing"] is False and done["desktop"] is True


def test_each_refusal_says_which_way_out_the_window_should_offer(installer):
    target = installer.program_dir()
    (target / "_internal").mkdir(parents=True)
    with (target / "_internal" / "python311.dll").open("w"):
        with pytest.raises(installer.Refused) as running:
            installer.do_install(False)
    assert running.value.code == "running"
    (target / "portable").write_text("", encoding="utf-8")
    with pytest.raises(installer.Refused) as portable:
        installer.do_install(False)
    assert portable.value.code == "portable"


def test_the_program_folder_is_deleted_only_once_the_uninstaller_has_ended(installer, monkeypatch):
    """It used to wait two seconds, while the closing message was still on the screen, and a slow
    reader left uninstall.exe running and the folder behind."""
    installer.program_dir().mkdir(parents=True)
    launched = []
    monkeypatch.setattr(installer.subprocess, "Popen", lambda args, **k: launched.append(args))
    installer.remove_folder_after_exit()
    script = launched[0][-1]
    assert f"Wait-Process -Id" in script and str(os.getpid()) in script
    assert script.index("Wait-Process") < script.index("Remove-Item")


def test_the_page_carries_the_apps_own_tokens_and_never_the_preview(tmp_path):
    sys.path.insert(0, str(ROOT / "packaging"))
    import installer_window
    staged = installer_window.stage_ui(tmp_path / "ui", ROOT)
    for name in ("index.html", "installer.css", "installer.js", "css/tokens.css", "css/base.css",
                 "fonts/fonts.css", "fonts/Inter-Variable.woff2", "fonts/Inter-OFL.txt"):
        assert (staged / name).exists(), name
    assert not (staged / "preview.js").exists()
    assert (installer_window.stage_ui(tmp_path / "look", ROOT, preview=True) / "preview.js").exists()
    # Every file the page asks for is one that was staged.
    html = (staged / "index.html").read_text(encoding="utf-8")
    for ref in re.findall(r'(?:href|src)="([^"]+)"', html):
        assert (staged / ref).exists(), ref


def test_quiet_never_opens_a_window(installer, monkeypatch):
    opened = []
    monkeypatch.setitem(sys.modules, "installer_window",
                        type(sys)("installer_window"))
    sys.modules["installer_window"].NoWindow = Exception
    sys.modules["installer_window"].run = lambda *a: opened.append(a) or 0
    assert installer.main() == 0                      # the fixture runs with --quiet
    assert opened == []
    assert (installer.program_dir() / "Herewise.exe").exists()

    monkeypatch.setattr(sys, "argv", ["Herewise-Setup.exe"])
    installer.shown.clear()
    assert installer.main() == 0
    assert len(opened) == 1, "without --quiet, and with the runtime there, the window is used"
    assert installer.shown == [], "and no message box as well"


def test_an_install_that_lost_its_entry_is_still_an_update(installer, monkeypatch):
    """0.1.6 in its folder with both shortcuts and no uninstall entry, on the owner's machine on
    2026-09-23: the installer called itself a fresh install."""
    target = installer.program_dir()
    (target / "_internal").mkdir(parents=True)
    (target / "_internal" / "VERSION").write_text("0.1.6", encoding="utf-8")
    monkeypatch.setattr(installer, "installed_version", lambda: None)
    assert installer.previous_version() == "0.1.6"
    done = installer.do_install(False)
    assert done["replacing"] is True and done["previous"] == "0.1.6"
    # And the entry is written again, so Installed apps lists it once more.
    assert ("entry", "0.2.0") in installer.calls


def test_nothing_installed_is_not_an_update(installer, monkeypatch):
    monkeypatch.setattr(installer, "installed_version", lambda: "0.1.6")   # a stale entry, no folder
    assert installer.previous_version() is None
