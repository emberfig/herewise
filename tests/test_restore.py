"""Known gap 14: restoring the register from a backup.

A restore replaces everything, so these check the two halves of its promise: a good backup comes back
whole and the register as it was is kept, and anything that should not be restored is refused with
nothing changed.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from rollcall import db
from rollcall.app import create_app

PASSWORD = "secret123"


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "data" / "rollcall.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                   "password": PASSWORD, "academic_session": "2026/2027"})
        c.data = tmp_path / "data"
        yield c


def make_account(client, username):
    role = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Viewer")
    made = client.post("/api/accounts", json={"username": username, "display_name": username.title(),
                                              "password": PASSWORD, "role_id": role})
    assert made.status_code == 200, made.text


def usernames(path):
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT username FROM accounts")}


def edit(path, sql):
    """Change a backup file in place. A backup is in WAL mode, so a change sits in a -wal file beside
    it until checkpointed; without this the bytes uploaded were the unedited file."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(sql)
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def inspect_bytes(client, content, filename="backup.db"):
    return client.post("/api/restore/inspect", files={"file": (filename, content, "application/octet-stream")})


def test_a_backup_replaces_the_register_and_the_register_as_it_was_is_kept(client):
    make_account(client, "before")
    backup = client.get("/api/backup").content
    make_account(client, "after")                       # only in the register, not in the backup

    looked = inspect_bytes(client, backup)
    assert looked.status_code == 200, looked.text
    body = looked.json()
    assert body["backup"]["accounts"] == ["lecturer", "before"]
    assert body["current"]["accounts"] == ["lecturer", "before", "after"]
    assert body["your_account_in_backup"] is True

    done = client.post("/api/restore", json={"token": body["token"], "password": PASSWORD})
    assert done.status_code == 200, done.text
    assert client.get("/api/me").status_code == 401     # everyone signs in again

    assert usernames(client.data / "rollcall.db") == {"lecturer", "before"}
    kept = client.data / "backups" / done.json()["kept"]
    assert usernames(kept) == {"lecturer", "before", "after"}   # what the restore replaced

    assert client.post("/api/login", json={"username": "lecturer", "password": PASSWORD}).status_code == 200
    entry = client.get("/api/audit").json()["entries"][0]
    assert entry["action"] == "backup.restore"
    assert "Dr Lecturer (lecturer) restored the file backup.db" in entry["sentence"]
    assert done.json()["kept"] in entry["sentence"]
    # The file waiting to be restored is gone, so a second copy of the register is not left lying about.
    assert not list((client.data / "restore-staging").glob("*.db"))


def test_the_wrong_password_changes_nothing(client):
    backup = client.get("/api/backup").content
    make_account(client, "after")
    token = inspect_bytes(client, backup).json()["token"]
    refused = client.post("/api/restore", json={"token": token, "password": "not-it"})
    assert refused.status_code == 403
    assert refused.json()["error"] == "That password is not right. Nothing has been changed."
    assert "after" in usernames(client.data / "rollcall.db")
    assert not (client.data / "backups").exists() or not list((client.data / "backups").glob("before-restore-*"))


def test_files_that_are_not_herewise_registers_are_refused(client, tmp_path):
    assert inspect_bytes(client, b"matric,name\n1,A\n").json()["error"] == \
        "This file is not a Herewise backup. It is not a database at all."

    other = tmp_path / "other.db"
    with sqlite3.connect(other) as conn:
        conn.execute("CREATE TABLE notes(text)")
    assert inspect_bytes(client, other.read_bytes()).json()["error"] == \
        "This file is a database, but not a Herewise register."

    newer = tmp_path / "newer.db"
    newer.write_bytes(client.get("/api/backup").content)
    edit(newer, f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    assert "made by a newer version of Herewise" in inspect_bytes(client, newer.read_bytes()).json()["error"]

    whole = client.get("/api/backup").content
    damaged = inspect_bytes(client, whole[: len(whole) // 2])
    assert damaged.status_code == 400
    assert damaged.json()["error"].startswith("This backup is damaged")

    # Nothing refused is kept waiting.
    assert not list((client.data / "restore-staging").glob("*.db"))


def test_a_backup_nobody_could_sign_in_to_is_refused(client, tmp_path):
    locked = tmp_path / "locked.db"
    locked.write_bytes(client.get("/api/backup").content)
    edit(locked, "UPDATE accounts SET disabled = 1")
    refused = inspect_bytes(client, locked.read_bytes())
    assert refused.status_code == 400
    assert refused.json()["error"].startswith("Nobody could sign in to this backup")


def test_a_copy_on_this_computer_can_be_restored_by_name_and_only_by_name(client):
    make_account(client, "before")
    backups_folder = client.data / "backups"
    backups_folder.mkdir(exist_ok=True)
    (backups_folder / "auto-20260921-090000-after-pull.db").write_bytes(client.get("/api/backup").content)
    make_account(client, "after")

    looked = client.post("/api/restore/inspect", data={"name": "auto-20260921-090000-after-pull.db"})
    assert looked.status_code == 200, looked.text
    assert looked.json()["label"] == "the copy auto-20260921-090000-after-pull.db"
    done = client.post("/api/restore", json={"token": looked.json()["token"], "password": PASSWORD})
    assert done.status_code == 200, done.text
    assert usernames(client.data / "rollcall.db") == {"lecturer", "before"}

    client.post("/api/login", json={"username": "lecturer", "password": PASSWORD})
    for name in ("../rollcall.db", "..\\rollcall.db", "rollcall.db", "missing.db"):
        refused = client.post("/api/restore/inspect", data={"name": name})
        assert refused.status_code == 400, name


def test_restoring_needs_its_own_permission_and_a_staged_file(client):
    backup = client.get("/api/backup").content
    make_account(client, "viewer")
    # A role that may take backups may not restore one until somebody ticks that too.
    role = client.post("/api/roles", json={"name": "Backups", "permissions": ["backup.run"]}).json()
    account = next(a for a in client.get("/api/accounts").json() if a["username"] == "viewer")
    client.post(f"/api/accounts/{account['id']}/role", json={"role_id": role["role_id"]})
    with TestClient(client.app) as theirs:
        theirs.post("/api/login", json={"username": "viewer", "password": PASSWORD})
        assert theirs.get("/api/backups").status_code == 200
        refused = theirs.post("/api/restore/inspect", files={"file": ("b.db", backup)})
        assert refused.status_code == 403
        assert refused.json()["error"] == "Your role does not allow this: restore from a backup."

    gone = client.post("/api/restore", json={"token": "0" * 32, "password": PASSWORD})
    assert gone.status_code == 400
    assert gone.json()["error"] == "That backup is no longer waiting to be restored. Choose it again."
    assert client.post("/api/restore", json={"token": "../rollcall", "password": PASSWORD}).status_code == 400
