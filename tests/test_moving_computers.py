"""Moving the data from one computer to another, asked for on 2026-09-23.

"create a backup and import all herewise data feature so when i set the real attendance on my laptop
i can easily move it all with all the data and import it into herewise on the teacher's laptop", then
"only the data, not the account name and password", from an optional "already used Herewise? Import
your data" on the first screen.

The file is the backup Settings, Backup already downloads. These act the move out with two registers,
one per laptop: the data comes across, the lecturer signs in with the account they made on the new
laptop, nobody signs in with an account from the old one, and the door this opens before an account
exists shuts the moment one does.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from rollcall.app import create_app

PASSWORD = "secret123"
THEIRS = {"username": "okonkwo", "display_name": "Dr Okonkwo", "password": "their-own-pass"}


@pytest.fixture
def my_laptop(tmp_path, k40_factory):
    app = create_app(tmp_path / "mine" / "rollcall.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                   "password": PASSWORD, "academic_session": "2026/2027",
                                   "device": {"name": "K40", "ip": "192.168.1.201", "port": 4370,
                                              "comm_key": 0}})
        level = next(l["id"] for l in c.get("/api/levels").json() if l["level_number"] == 200)
        preview = c.post(f"/api/levels/{level}/roster/preview",
                         files={"file": ("roster.csv", ROSTER.read_bytes(), "text/csv")})
        c.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
        c.post("/api/courses", json={"level_id": level, "code": "200 Level"})
        course = c.get("/api/courses").json()[0]
        made = c.post("/api/sessions", json={"course_id": course["id"], "date": date.today().isoformat(),
                                             "start_time": "09:00", "end_time": "11:00", "kind": "manual"})
        person = c.get(f"/api/courses/{course['id']}/students").json()[0]["person_id"]
        marked = c.post(f"/api/sessions/{made.json()['id']}/marks",
                        json={"person_id": person, "status": "present", "note": "Signed the paper sheet."})
        assert marked.status_code == 200, marked.text
        c.class_id = made.json()["id"]
        yield c


@pytest.fixture
def their_laptop(tmp_path, k40_factory):
    app = create_app(tmp_path / "theirs" / "rollcall.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.data = tmp_path / "theirs"
        yield c


def carry(my_laptop) -> bytes:
    """What goes on the USB stick: the file Settings, Backup downloads."""
    response = my_laptop.get("/api/backup")
    assert response.status_code == 200
    # Named for the button, and readable on a USB stick: herewise-data-2026-09-23-2152.db.
    assert re.search(r'filename="herewise-data-\d{4}-\d{2}-\d{2}-\d{4}\.db"',
                     response.headers["content-disposition"])
    return response.content


def look(their_laptop, content: bytes):
    return their_laptop.post("/api/setup/import/inspect",
                             files={"file": ("herewise-data-2026-09-23-2152.db", content, "application/octet-stream")})


def test_the_data_comes_across_and_the_lecturer_signs_in_with_their_own_account(my_laptop, their_laptop):
    students = len(my_laptop.get("/api/levels/2/students").json()["students"])
    courses = [c["code"] for c in my_laptop.get("/api/courses").json()]
    assert their_laptop.get("/api/setup/status").json()["needs_setup"] is True

    looked = look(their_laptop, carry(my_laptop))
    assert looked.status_code == 200, looked.text
    held = looked.json()["backup"]
    assert held["students"] == students and held["courses"] == 1 and held["corrections"] == 1
    assert looked.json()["terminal"]["ip"] == "192.168.1.201", "the terminal comes along, and says so"

    brought = their_laptop.post("/api/setup/import", json={"token": looked.json()["token"], **THEIRS})
    assert brought.status_code == 200, brought.text
    assert brought.json()["accounts_switched_off"] == 1
    # Signed in straight away, as setup does, with the account they have just made.
    me = their_laptop.get("/api/me").json()
    assert me["username"] == "okonkwo" and me["is_owner"] is True
    assert their_laptop.get("/api/setup/status").json()["needs_setup"] is False

    assert len(their_laptop.get("/api/levels/2/students").json()["students"]) == students
    assert [c["code"] for c in their_laptop.get("/api/courses").json()] == courses
    log = their_laptop.get("/api/audit").json()["entries"]
    assert any(e["action"] == "backup.import" for e in log)
    assert not list((their_laptop.data / "restore-staging").glob("*.db"))


def test_nobody_signs_in_with_an_account_from_the_other_computer(my_laptop, their_laptop):
    looked = look(their_laptop, carry(my_laptop)).json()
    their_laptop.post("/api/setup/import", json={"token": looked["token"], **THEIRS})
    their_laptop.post("/api/logout")
    refused = their_laptop.post("/api/login", json={"username": "lecturer", "password": PASSWORD})
    assert refused.status_code in (401, 403), refused.text
    # Kept switched off rather than deleted, because the correction still says who signed it.
    accounts = {a["username"]: a for a in _accounts(their_laptop)}
    assert accounts["lecturer"]["disabled"] is True
    with sqlite3.connect(their_laptop.data / "rollcall.db") as conn:
        signed = conn.execute("SELECT a.username FROM attendance_marks m JOIN accounts a ON a.id = m.account_id").fetchall()
        hashes = [r[0] for r in conn.execute("SELECT password_hash FROM accounts WHERE username = 'lecturer'")]
    assert signed == [("lecturer",)]
    assert hashes == ["moved"], "the old password is not carried in any form"


def _accounts(client):
    client.post("/api/login", json={"username": THEIRS["username"], "password": THEIRS["password"]})
    return client.get("/api/accounts").json()


def test_the_same_username_as_before_can_be_chosen(my_laptop, their_laptop):
    looked = look(their_laptop, carry(my_laptop)).json()
    done = their_laptop.post("/api/setup/import", json={"token": looked["token"], "username": "lecturer",
                                                         "display_name": "Dr Lecturer", "password": "a-new-one"})
    assert done.status_code == 200, done.text
    their_laptop.post("/api/logout")
    assert their_laptop.post("/api/login", json={"username": "lecturer", "password": PASSWORD}).status_code != 200
    assert their_laptop.post("/api/login", json={"username": "lecturer", "password": "a-new-one"}).status_code == 200
    names = {a["username"] for a in their_laptop.get("/api/accounts").json()}
    assert names == {"lecturer", "lecturer-previous"}


def test_a_short_password_is_refused_before_anything_changes(my_laptop, their_laptop):
    looked = look(their_laptop, carry(my_laptop)).json()
    refused = their_laptop.post("/api/setup/import", json={"token": looked["token"], "username": "x",
                                                            "display_name": "X", "password": "123"})
    assert refused.status_code == 400 and "at least 6" in refused.json()["error"]
    assert their_laptop.get("/api/setup/status").json()["needs_setup"] is True
    assert their_laptop.get("/api/levels").json() is not None


def test_the_door_shuts_once_anybody_has_an_account(my_laptop):
    """Replacing a register somebody uses needs the signed-in restore and a password."""
    my_laptop.post("/api/logout")
    refused = look(my_laptop, b"SQLite format 3\x00")
    assert refused.status_code == 400 and "already been done" in refused.json()["error"]
    refused = my_laptop.post("/api/setup/import", json={"token": "0" * 32, **THEIRS})
    assert refused.status_code == 400 and "already been done" in refused.json()["error"]


def test_a_file_that_is_not_a_register_changes_nothing(their_laptop, tmp_path):
    refused = look(their_laptop, b"not a database")
    assert refused.status_code == 400 and "not a Herewise backup" in refused.json()["error"]
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE things(x)")
    conn.commit()
    conn.close()
    assert look(their_laptop, other.read_bytes()).status_code == 400
    assert their_laptop.get("/api/setup/status").json()["needs_setup"] is True
    assert not list((their_laptop.data / "restore-staging").glob("*.db"))


def test_changing_your_mind_throws_the_staged_copy_away(my_laptop, their_laptop):
    looked = look(their_laptop, carry(my_laptop)).json()
    assert list((their_laptop.data / "restore-staging").glob("*.db"))
    assert their_laptop.delete(f"/api/setup/import/{looked['token']}").status_code == 200
    assert not list((their_laptop.data / "restore-staging").glob("*.db"))
    assert their_laptop.get("/api/setup/status").json()["needs_setup"] is True
