"""Deleting a level's roster and everything on it, asked for on 2026-09-23.

"set it so that I can delete the roster and when i do it delete a roster everything related to that
roster will be deleted including the classes and the attendance and courses", then, in the same
session: "if i delete a level it deletes their fingerprints off the terminal, do not allow deleting
of rosters if not connected to the terminal".

So the terminal goes first and the register only follows once the terminal reads back without the
level's block, the IDs are retired so a pull cannot bring the deleted attendance back and no new
student is handed one, and the database's refusal to delete attendance is lifted for that one
transaction and nowhere else.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from fake_zk import FakeFinger, FakeRecord, FakeUser
from rollcall import db
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "clearing.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        yield c


def setup_with_roster(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})
    level = next(l for l in client.get("/api/levels").json() if l["level_number"] == 200)
    preview = client.post(f"/api/levels/{level['id']}/roster/preview",
                          files={"file": ("roster.csv", ROSTER.read_bytes(), "text/csv")})
    client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    client.post("/api/courses", json={"level_id": level["id"], "code": "200 Level"})
    return level, client.get("/api/courses").json()[0]


def a_full_level(client, fake):
    """A roster on the terminal with fingers, scans pulled into a class, and a correction."""
    level, course = setup_with_roster(client)
    assert client.post("/api/devices/1/push", json={"level_id": level["id"]}).status_code == 200
    students = client.get(f"/api/courses/{course['id']}/students").json()
    for s in students[:5]:
        fake.templates[(int(s["device_user_id"]), 6)] = FakeFinger(int(s["device_user_id"]), 6)
    # A member of staff on the terminal, who is nothing to do with the level and must stay.
    fake.users[5] = FakeUser(5, "5", "DR LECTURER", 14)
    fake.templates[(5, 1)] = FakeFinger(5, 1)
    made = client.post("/api/sessions", json={"course_id": course["id"], "date": date.today().isoformat(),
                                              "start_time": "09:00", "end_time": "11:00", "kind": "manual"})
    session_id = made.json()["id"]
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(9, 30)))
                    for s in students[:3]] + [FakeRecord(user_id="5", timestamp=datetime.combine(
                        date.today(), time(9, 31)))]
    assert client.post("/api/devices/1/pull", json={}).status_code == 200
    marked = client.post(f"/api/sessions/{session_id}/marks",
                         json={"person_id": students[4]["person_id"], "status": "present",
                               "note": "Signed the paper sheet."})
    assert marked.status_code == 200, marked.text
    return level, course, students


def test_the_dialog_is_told_everything_that_will_go(client, fake):
    level, course, students = a_full_level(client, fake)
    preview = client.get(f"/api/levels/{level['id']}/clear").json()
    assert preview["students"] == len(client.get(f"/api/levels/{level['id']}/students").json()["students"])
    assert preview["courses"] == 1 and preview["classes"] == 1
    assert preview["scans"] == 3, "the staff scan is not the level's"
    assert preview["corrections"] == 1
    assert preview["on_terminal"] == preview["students"]


def test_deleting_a_roster_takes_everything_on_it_and_the_terminal_first(client, fake, tmp_path):
    level, course, students = a_full_level(client, fake)
    done = client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 level"})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["courses"] == 1 and body["classes"] == 1 and body["scans"] == 3

    # The terminal: every student and their fingers gone, the member of staff and theirs still there.
    assert set(fake.users) == {5}
    assert set(fake.templates) == {(5, 1)}
    assert len(fake.records) == 4, "the terminal's own scan log is left alone"

    # The register: nothing of the level left, and the level itself still there, empty.
    assert client.get("/api/courses").json() == []
    after = next(l for l in client.get("/api/levels").json() if l["id"] == level["id"])
    assert after["students"] == 0 and after["can_remove"] is True
    conn = db.connect(tmp_path / "clearing.db")
    for table in ("people", "attendance_marks", "class_sessions", "courses", "course_enrolments",
                  "level_memberships", "roster_imports", "register_templates", "fingers"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}"
                             + (" WHERE role = 'student'" if table == "people" else "")).fetchone()[0]
        assert count == 0, table
    assert [r[0] for r in conn.execute("SELECT device_user_id FROM punches")] == ["5"]
    assert conn.execute("SELECT first_id, last_id FROM retired_ids").fetchone()[:] == (
        2001, max(int(s["device_user_id"]) for s in students))
    # The guards are back: nothing else in the app can delete a scan or a correction.
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert {"punches_immutable_delete", "marks_immutable_delete", "requests_no_delete"} <= triggers
    with pytest.raises(Exception, match="immutable"):
        conn.execute("DELETE FROM punches")
    assert "level.clear" in [r[0] for r in conn.execute("SELECT action FROM audit_log")]
    assert list((tmp_path / "backups").glob("*before-deleting-a-roster*"))


def test_nothing_is_deleted_while_the_terminal_does_not_answer(client, fake):
    level, course, students = a_full_level(client, fake)
    fake.reachable = False
    refused = client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 Level"})
    assert refused.status_code >= 400
    assert "did not answer" in refused.json()["error"]
    assert "nothing was deleted" in refused.json()["error"]
    assert len(client.get("/api/courses").json()) == 1
    assert client.get(f"/api/levels/{level['id']}/clear").json()["students"] == len(students)


def test_a_mistyped_name_touches_neither_the_terminal_nor_the_register(client, fake):
    level, course, students = a_full_level(client, fake)
    fake.calls.clear()
    refused = client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "300 Level"})
    assert refused.status_code == 400 and "Type 200 Level exactly" in refused.json()["error"]
    assert "delete_user" not in fake.calls
    assert len(client.get("/api/courses").json()) == 1


def test_a_pull_afterwards_does_not_bring_the_deleted_attendance_back(client, fake, tmp_path):
    level, course, students = a_full_level(client, fake)
    client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 Level"})
    pulled = client.post("/api/devices/1/pull", json={}).json()
    assert pulled["retired"] == 3 and pulled["new"] == 0
    assert "3 from a deleted roster left out" in pulled["message"]
    conn = db.connect(tmp_path / "clearing.db")
    assert [r[0] for r in conn.execute("SELECT device_user_id FROM punches")] == ["5"]
    # Only the terminal user the register never had is unmatched; none of the level's scans are.
    assert [u["device_user_id"] for u in client.get("/api/punches/unmatched").json()] == ["5"]


def test_a_new_roster_is_numbered_after_the_deleted_one(client, fake):
    level, course, students = a_full_level(client, fake)
    highest = max(int(s["device_user_id"]) for s in students)
    client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 Level"})
    preview = client.post(f"/api/levels/{level['id']}/roster/preview",
                          files={"file": ("roster.csv", ROSTER.read_bytes(), "text/csv")})
    client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    again = client.get(f"/api/levels/{level['id']}/students").json()["students"]
    assert min(int(s["device_user_id"]) for s in again) == highest + 1


def test_a_class_taking_attendance_stops_it(client, fake):
    level, course = setup_with_roster(client)
    assert client.post(f"/api/courses/{course['id']}/live").status_code == 200
    refused = client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 Level"})
    assert refused.status_code == 400 and "End it first" in refused.json()["error"]


def test_removing_an_empty_level_needs_the_terminal_and_clears_its_block(client, fake):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})
    level = next(l for l in client.get("/api/levels").json() if l["level_number"] == 500)
    fake.users[5003] = FakeUser(5003, "5003", "LEFT FROM BEFORE")
    fake.reachable = False
    refused = client.delete(f"/api/levels/{level['id']}")
    assert refused.status_code >= 400 and "did not answer" in refused.json()["error"]
    assert any(l["id"] == level["id"] for l in client.get("/api/levels").json())
    fake.reachable = True
    assert client.delete(f"/api/levels/{level['id']}").status_code == 200
    assert 5003 not in fake.users


def test_the_terminal_can_still_be_cleared_after_a_roster_is_deleted(client, fake):
    """Reported 2026-09-23: "15 scans could not be confirmed as stored. The device was not cleared",
    every one of them from the dummy 200 Level the owner had just deleted. A pull leaves those out on
    purpose, and the check before clearing counted them as missing, so the terminal could never be
    cleared again."""
    level, course, students = a_full_level(client, fake)
    client.post(f"/api/levels/{level['id']}/clear", json={"confirm": "200 Level"})
    assert len(fake.records) == 4                        # 3 from the deleted roster, 1 from staff

    cleared = client.post("/api/devices/1/clear-attendance", json={"confirm_serial": fake.serial})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] == 4 and cleared.json()["from_deleted_roster"] == 3
    assert fake.records == []
    log = [e for e in client.get("/api/audit").json()["entries"] if e["action"] == "device.clear_attendance"]
    assert "3 from a deleted roster, not kept" in log[0]["sentence"]


def test_a_scan_that_really_is_missing_still_stops_the_clear(client, fake, monkeypatch):
    """The check keeps its teeth for everything else: a scan the register did not store blocks it."""
    level, course, students = a_full_level(client, fake)
    from rollcall import services
    real = services.store_punches
    monkeypatch.setattr(services, "store_punches",
                        lambda conn, device_id, records, *a, **k: real(conn, device_id, records[:-1], *a, **k))
    fake.records.append(FakeRecord(user_id="5", timestamp=fake.records[-1].timestamp.replace(minute=59)))
    refused = client.post("/api/devices/1/clear-attendance", json={"confirm_serial": fake.serial})
    assert refused.status_code == 400 and "could not be confirmed as stored" in refused.json()["error"]
    assert len(fake.records) == 5
