"""The correction drawer's contract, and the figures a course card shows.

Both are new shapes the screens render without working anything out for themselves
(docs/COMPONENT-GUIDE.md): GET /api/sessions/{id}/students/{person_id} and the `figures` block on
GET /api/courses.
"""
from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from fake_zk import FakeRecord
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "drawer.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        yield c


def course_with_a_class(client, fake, scan_for=2):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})
    level = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 200)
    preview = client.post(f"/api/levels/{level}/roster/preview",
                          files={"file": ("roster.csv", ROSTER.read_bytes(), "text/csv")})
    client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    client.post("/api/courses", json={"level_id": level, "code": "200 Level"})
    course = client.get("/api/courses").json()[0]
    students = client.get(f"/api/courses/{course['id']}/students").json()
    today = date.today().isoformat()
    session_id = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                                    "start_time": "08:00", "end_time": "10:00",
                                                    "kind": "device"}).json()["id"]
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(8, 5)))
                    for s in students[:scan_for]]
    client.post("/api/devices/1/pull", json={})
    return course, session_id, students


def test_a_box_carries_its_scan_its_marks_and_who_wrote_each(client, fake):
    course, session_id, students = course_with_a_class(client, fake)
    person = students[0]["person_id"]

    cell = client.get(f"/api/sessions/{session_id}/students/{person}").json()
    assert cell["status"] == "present"
    assert cell["first_scan"].endswith("08:05:00")
    assert cell["history"] == []
    assert cell["student"]["matric_no"] == students[0]["matric_no"]
    assert cell["session"]["course_code"] == course["code"]

    client.post(f"/api/sessions/{session_id}/marks",
                json={"person_id": person, "status": "absent", "note": "Scanned for a friend."})
    client.post(f"/api/sessions/{session_id}/marks",
                json={"person_id": person, "status": "present", "note": "The video shows they were there."})
    after = client.get(f"/api/sessions/{session_id}/students/{person}").json()
    assert after["status"] == "marked_present"
    # Append-only: the scan is still there, both marks are, oldest first, and each says who and why.
    assert after["first_scan"] == cell["first_scan"]
    assert [(m["status"], m["by"], m["note"]) for m in after["history"]] == [
        ("absent", "Dr Lecturer", "Scanned for a friend."),
        ("present", "Dr Lecturer", "The video shows they were there.")]


def test_a_box_shows_a_request_nobody_has_decided_yet(client, fake):
    course, session_id, students = course_with_a_class(client, fake)
    person = students[3]["person_id"]
    rep_role = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Course rep")
    client.post("/api/accounts", json={"username": "rep", "display_name": "Chidi Umeh",
                                       "password": "secret123", "role_id": rep_role})
    client.post("/api/logout")
    client.post("/api/login", json={"username": "rep", "password": "secret123"})
    client.post(f"/api/sessions/{session_id}/correction-requests",
                json={"person_id": person, "status": "present", "note": "Signed the paper sheet."})

    cell = client.get(f"/api/sessions/{session_id}/students/{person}").json()
    assert [(r["status"], r["by"], r["note"]) for r in cell["pending_requests"]] == [
        ("present", "Chidi Umeh", "Signed the paper sheet.")]
    assert cell["history"] == []       # nothing is on the register until someone decides


def test_a_course_card_gets_its_four_numbers_from_the_register(client, fake):
    course, session_id, students = course_with_a_class(client, fake, scan_for=200)
    figures = next(c for c in client.get("/api/courses?with_figures=true").json()
                   if c["id"] == course["id"])["figures"]
    assert figures["classes_held"] == 1
    assert figures["last_class"] == {"session_id": session_id, "date": date.today().isoformat(),
                                     "start_time": "08:00", "present": 200, "registered": 258}
    assert figures["average_percent"] == pytest.approx(200 / 258 * 100, abs=0.2)
    assert figures["below_threshold"] == 58        # everyone who did not scan, at a 75% pass mark
    assert figures["can_still_reach"] + figures["cannot_reach"] == figures["below_threshold"]
    # Without the flag the figures are not computed at all, because each one is a full pass.
    assert "figures" not in client.get("/api/courses").json()[0]


def test_a_cancelled_class_is_not_counted_as_held(client, fake):
    course, session_id, _ = course_with_a_class(client, fake)
    client.post(f"/api/sessions/{session_id}/cancel", json={"note": "Hall double booked."})
    figures = client.get(f"/api/courses/{course['id']}?with_figures=true").json()["figures"]
    assert figures["classes_held"] == 0
    assert figures["cancelled_classes"] == 1


def test_a_class_cancelled_by_mistake_can_be_restored(client, fake):
    """Known gap 15. Cancelling is a judgement made in a hurry, and until now a wrong one could
    only be undone by editing SQLite."""
    course, session_id, students = course_with_a_class(client, fake, scan_for=5)
    client.post(f"/api/sessions/{session_id}/cancel", json={"note": "Wrong date, I meant last week."})
    assert client.get(f"/api/courses/{course['id']}?with_figures=true").json()["figures"]["classes_held"] == 0

    restored = client.post(f"/api/sessions/{session_id}/restore", json={"note": "Cancelled the wrong one."})
    assert restored.status_code == 200, restored.text
    figures = client.get(f"/api/courses/{course['id']}?with_figures=true").json()["figures"]
    assert figures["classes_held"] == 1 and figures["cancelled_classes"] == 0
    # Nothing was lost: the scans are still the register.
    assert client.get(f"/api/sessions/{session_id}/register").json()["totals"]["present"] == 5
    # Both decisions are in the log, with the cancellation's own reason kept.
    actions = [r for r in client.get("/api/audit").json()["entries"]
               if r["action"].startswith("session.")]
    assert [a["action"] for a in actions][:2] == ["session.restore", "session.cancel"]
    assert "Wrong date, I meant last week." in actions[0]["detail"]

    assert client.post(f"/api/sessions/{session_id}/restore", json={}).status_code == 400


def test_restoring_a_class_needs_the_permission_to_cancel_one(client, fake):
    course, session_id, _ = course_with_a_class(client, fake)
    client.post(f"/api/sessions/{session_id}/cancel", json={"note": "Hall double booked."})
    viewer = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Viewer")
    client.post("/api/accounts", json={"username": "viewer", "display_name": "Viewer",
                                       "password": "secret123", "role_id": viewer})
    client.post("/api/logout")
    client.post("/api/login", json={"username": "viewer", "password": "secret123"})
    refused = client.post(f"/api/sessions/{session_id}/restore", json={})
    assert refused.status_code == 403
    assert refused.json()["error"] == "Your role does not allow this: create and cancel classes."


def test_the_activity_log_names_the_student_not_a_row_number(client, fake):
    """Screen 38 read "Corrected a student's attendance: session 5 person 26 present", which nobody
    can check against a paper sheet: the numbers are this database's own. Checklist Design, Audit
    log, affected resource (2026-09-21)."""
    course, session_id, students = course_with_a_class(client, fake)
    student = students[0]
    client.post(f"/api/sessions/{session_id}/marks",
                json={"person_id": student["person_id"], "status": "absent",
                      "note": "Scanned for a friend."})
    client.post("/api/excusals", json={"person_id": student["person_id"],
                                       "date_from": "2026-09-14", "date_to": "2026-09-16",
                                       "category": "medical", "note": "Hospital letter seen."})

    entries = client.get("/api/audit").json()["entries"]
    correction = next(e for e in entries if e["action"] == "attendance.mark")
    excusal = next(e for e in entries if e["action"] == "excusal.create")

    for entry in (correction, excusal):
        assert student["matric_no"] in entry["sentence"], entry["sentence"]
        assert student["surname"] in entry["sentence"], entry["sentence"]
        assert f"person {student['person_id']}" not in entry["sentence"], entry["sentence"]
    # The correction also says which class it was, by course and date, not by row.
    assert course["code"] in correction["sentence"], correction["sentence"]
    assert f"session {session_id}" not in correction["sentence"], correction["sentence"]


def test_reading_the_scans_from_the_terminal_reads_as_a_sentence(client, fake):
    """"punches.import.network: 229 read, 229 new" was the raw action name on screen 38: the name
    was built in the db.audit call, so the test that every action has a sentence never saw it."""
    course_with_a_class(client, fake)
    entries = client.get("/api/audit").json()["entries"]
    pull = next(e for e in entries if e["action"] == "punches.import.network")
    assert pull["sentence"].startswith("Read the scans from the terminal over the cable")
    assert "punches.import" not in pull["sentence"]
    assert pull["group"] == "Attendance"
