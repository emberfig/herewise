"""Known gap 3 (accounts could not recover) and known gap 17 (the audit log could not be read).

Before this an account whose password was forgotten had no way back, a disabled account could not
be turned on again, and `GET /api/audit` took only a limit and returned `str(body)` as its detail.
"""
import pytest
from fastapi.testclient import TestClient

from rollcall import audit, db
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "accounts.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.db_path = tmp_path / "accounts.db"
        yield c


def setup(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})


def make_viewer(client, username="viewer"):
    role = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Viewer")
    return client.post("/api/accounts", json={"username": username, "display_name": "A Viewer",
                                              "password": "secret123", "role_id": role}).json()["account_id"]


def test_a_forgotten_password_can_be_set_again_and_ends_their_sessions(client):
    setup(client)
    account_id = make_viewer(client)

    # They are signed in somewhere with the old password.
    with TestClient(client.app) as theirs:
        assert theirs.post("/api/login", json={"username": "viewer", "password": "secret123"}).status_code == 200
        assert theirs.get("/api/me").status_code == 200

        done = client.post(f"/api/accounts/{account_id}/password", json={"password": "new-secret"})
        assert done.status_code == 200, done.text
        # A forgotten password often means somebody else has it, so every session ends.
        assert theirs.get("/api/me").status_code == 401

    assert client.post("/api/login", json={"username": "viewer", "password": "secret123"}).status_code == 401
    assert client.post("/api/login", json={"username": "viewer", "password": "new-secret"}).status_code == 200


def test_a_disabled_account_can_be_turned_back_on(client):
    setup(client)
    account_id = make_viewer(client)
    client.post(f"/api/accounts/{account_id}/disable")
    assert client.post("/api/login", json={"username": "viewer", "password": "secret123"}).status_code == 401

    back = client.post(f"/api/accounts/{account_id}/enable")
    assert back.status_code == 200, back.text
    assert back.json()["disabled"] is False
    assert client.post("/api/login", json={"username": "viewer", "password": "secret123"}).status_code == 200
    # That login moved this client to the viewer, who cannot manage accounts.
    client.post("/api/login", json={"username": "lecturer", "password": "secret123"})
    assert client.post(f"/api/accounts/{account_id}/enable").status_code == 400   # already on


def test_neither_recovery_route_is_open_to_a_role_that_cannot_manage_accounts(client):
    setup(client)
    account_id = make_viewer(client)
    client.post("/api/logout")
    client.post("/api/login", json={"username": "viewer", "password": "secret123"})
    for call in (lambda: client.post(f"/api/accounts/{account_id}/password", json={"password": "x1234567"}),
                 lambda: client.post(f"/api/accounts/{account_id}/enable")):
        refused = call()
        assert refused.status_code == 403
        assert refused.json()["error"] == "Your role does not allow this: manage accounts."


def test_the_command_line_reset_is_the_way_back_for_the_only_owner(client, monkeypatch, capsys):
    """The sole owner has nobody above them, so the way back is on this computer itself."""
    setup(client)
    from rollcall import __main__ as entry

    monkeypatch.setattr(entry, "default_db_path", lambda: client.db_path)
    monkeypatch.setattr(entry.getpass, "getpass", lambda _: "brand-new-one")
    assert entry.reset_password("lecturer") == 0
    assert client.post("/api/login", json={"username": "lecturer", "password": "brand-new-one"}).status_code == 200

    # It refuses a name it does not have, rather than doing nothing quietly.
    assert entry.reset_password("nobody") == 1


def test_the_log_is_narrowed_and_reads_as_sentences(client):
    setup(client)
    make_viewer(client)
    client.put("/api/settings", json={"backup_keep": "20"})

    data = client.get("/api/audit").json()
    by_action = {e["action"]: e for e in data["entries"]}
    # Not "settings.update" beside "{'backup_keep': '20'}".
    assert by_action["settings.update"]["sentence"] == "Changed settings: backup keep to 20"
    assert by_action["account.create"]["sentence"] == "Made an account: viewer as Viewer"
    assert by_action["setup"]["sentence"] == "Set this computer up and made the first account"
    assert by_action["settings.update"]["group"] == "Setting up"
    assert by_action["account.create"]["group"] == "People"
    assert by_action["setup"]["by"] == "Dr Lecturer"
    assert [a["display_name"] for a in data["actors"]] == ["Dr Lecturer"]

    only_people = client.get("/api/audit?group=People").json()["entries"]
    assert {e["group"] for e in only_people} == {"People"}
    assert client.get("/api/audit?date_from=2020-01-01&date_to=2020-01-02").json()["entries"] == []
    assert client.get("/api/audit?date_from=yesterday").status_code == 400


def test_the_log_exports_as_a_csv_excel_can_open(client):
    setup(client)
    client.put("/api/settings", json={"backup_keep": "20"})
    csv = client.get("/api/audit/export")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    body = csv.content.decode("utf-8-sig")
    assert body.startswith("When,Who,Their role,What happened,Action,What it touched")
    assert "Changed settings: backup keep to 20" in body
    # Excel on Windows reads a CSV as Windows-1252 unless it starts with a BOM.
    assert csv.content.startswith(b"\xef\xbb\xbf")
    # Exporting is itself in the log.
    assert any(e["action"] == "audit.export" for e in client.get("/api/audit").json()["entries"])


def test_an_action_with_no_sentence_written_for_it_still_reads(client):
    assert audit.sentence("something.new", "a detail") == "something.new: a detail"
    assert audit.sentence("session.cancel", "") == "Cancelled a class"
    assert audit.group_of("something.new") == "Other"


def test_every_action_the_code_writes_has_a_sentence():
    """The first version of this map was written from guessed names, so half the log still read as
    "correction.decide: approved" on screen. The names come from the db.audit calls themselves."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "rollcall"
    written = set()
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Any number of dotted parts: "backup.auto.failed" has two dots, and a pattern allowing one
        # let it through with no sentence until 2026-09-21.
        for call in re.finditer(r"db\.audit\(\s*[^,]+,\s*[^,]+,\s*\"([a-z_]+(?:\.[a-z_]+)*)\"", text):
            written.add(call.group(1))
        # An action name assembled in the call, f"punches.import.{source}", is invisible to the
        # pattern above, and both of its names went a week with no sentence. A module that builds
        # one names it in AUDIT_ACTIONS instead, and those count as written too.
        for value in re.findall(r"AUDIT_ACTIONS = \{([^}]*)\}", text, re.S):
            written.update(re.findall(r"\"([a-z_]+(?:\.[a-z_]+)+)\"", value))
    assert written, "no db.audit calls found, so this test is not checking anything"
    assert "punches.import.network" in written, "the AUDIT_ACTIONS names are not being read"

    missing = sorted(written - set(audit.SENTENCES))
    assert not missing, f"no sentence written for: {missing}"
    ungrouped = sorted(a for a in written if audit.group_of(a) == "Other")
    assert not ungrouped, f"not in any group, so the Kind filter cannot find them: {ungrouped}"


def test_the_way_back_in_names_the_command_this_build_actually_has(client, monkeypatch):
    """Screen 37 printed "python -m rollcall reset-password <username>" wherever it was running.
    The only owner who is locked out is using the installed app, which carries no Python and no
    source, so that line could not work for the one person it is written for."""
    from rollcall import about

    setup(client)
    assert client.get("/api/about").json()["reset_password_command"] == \
        "python -m rollcall reset-password <username>"

    monkeypatch.setattr(about.sys, "frozen", True, raising=False)
    monkeypatch.setattr(about.sys, "executable", r"C:\Users\somebody\Programs\Herewise\Herewise.exe")
    installed = client.get("/api/about").json()["reset_password_command"]
    assert installed.startswith('"')
    assert installed.endswith(r'Herewise.exe" reset-password <username>')
    assert "python" not in installed
