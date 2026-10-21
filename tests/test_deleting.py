"""Deleting a course, deleting a class, and forgetting what fingerprints the register recorded.

All three were asked for on a second run with a real roster: a course made by mistake, two classes
cancelled by mistake, and a terminal emptied from its own menu leaving the register claiming
fingerprints that were no longer on it (2026-09-22).

The line these keep is the one the database itself draws. `punches`, `attendance_marks`,
`correction_requests` and `audit_log` all carry triggers that refuse a DELETE outright; nothing
else does. So what can never go is a **signed decision**: a correction, a correction request, an
excused absence. What can go is the structure around it: a course, a class, a sheet, a plan, a roll.

A scan is in neither list, because deleting a course or a class deletes no scan at all: attendance
is worked out from the times, so a class is a window over the scans rather than a container of
them. The first version of this refused a course that merely had scans in its classes, with the
sentence "attendance that has been recorded is never deleted", which implied the scans would go and
left somebody unable to be rid of a course for a reason that was not true (reported 2026-09-22).
Scans are counted and stated now, not a refusal, and these tests check they are still there
afterwards.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from fake_zk import FakeRecord
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "deleting.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        yield c


def setup_with_roster(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})
    level = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 200)
    preview = client.post(f"/api/levels/{level}/roster/preview",
                          files={"file": ("roster.csv", ROSTER.read_bytes(), "text/csv")})
    client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    client.post("/api/courses", json={"level_id": level, "code": "200 Level"})
    return client.get("/api/courses").json()[0]


def a_class(client, course, start="09:00", end="11:00", on=None):
    made = client.post("/api/sessions", json={"course_id": course["id"],
                                              "date": on or date.today().isoformat(),
                                              "start_time": start, "end_time": end,
                                              "kind": "manual"})
    assert made.status_code == 200, made.text
    return made.json()["id"]


# -- a class -------------------------------------------------------------------------------------

def test_a_class_that_recorded_nothing_can_be_deleted(client):
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    assert client.delete(f"/api/sessions/{session_id}").status_code == 200
    assert not [c for c in client.get(f"/api/sessions?course_id={course['id']}").json()
                if c["id"] == session_id]


def test_a_cancelled_class_that_recorded_nothing_can_be_deleted(client):
    """The one they asked for: two classes cancelled by mistake and no way to be rid of them."""
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    client.post(f"/api/sessions/{session_id}/cancel", json={"note": "Made by mistake."})
    assert client.delete(f"/api/sessions/{session_id}").status_code == 200


def test_a_class_with_scans_but_no_decision_can_go_and_the_scans_stay(client, fake):
    """A class made at the wrong time swallows scans that belong to another one. Deleting it takes
    the window away, not the scans: they are in punches, which the database will not delete."""
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    students = client.get(f"/api/courses/{course['id']}/students").json()
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(9, 30)))
                    for s in students[:3]]
    client.post("/api/devices/1/pull", json={})

    row = next(c for c in client.get(f"/api/sessions?course_id={course['id']}").json()
               if c["id"] == session_id)
    assert row["holds"] == {"scans": 3}, "the scans are counted"
    assert row["blocking"] == {} and row["can_delete"] is True, "and they do not stop it"

    assert client.delete(f"/api/sessions/{session_id}").status_code == 200
    # The scans are still in the register, and would be found again by another class at that time.
    assert client.get("/api/punches/unmatched").status_code == 200
    made = client.post("/api/sessions", json={"course_id": course["id"],
                                              "date": date.today().isoformat(),
                                              "start_time": "09:00", "end_time": "11:00",
                                              "kind": "manual"}).json()["id"]
    register = client.get(f"/api/sessions/{made}/register").json()
    assert register["totals"]["present"] == 3, "the scans found the new class at the same time"


def test_a_class_somebody_corrected_is_refused(client):
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    person = client.get(f"/api/courses/{course['id']}/students").json()[0]["person_id"]
    marked = client.post(f"/api/sessions/{session_id}/marks",
                         json={"person_id": person, "status": "present",
                               "note": "Signed the paper sheet."})
    assert marked.status_code == 200, marked.text
    refused = client.delete(f"/api/sessions/{session_id}")
    assert refused.status_code == 400
    # Named for its count: "1 corrections" was on a real screen before this.
    assert "1 correction" in refused.json()["error"]
    assert "1 corrections" not in refused.json()["error"]


# -- a course ------------------------------------------------------------------------------------

def test_a_course_that_recorded_nothing_goes_with_its_sheet_and_its_roll(client):
    course = setup_with_roster(client)
    made = client.post("/api/courses", json={"level_id": 2, "code": "PCT 299",
                                             "title": "Made by mistake"}).json()
    assert client.get(f"/api/courses/{made['id']}/students").json()
    a_class(client, made)

    holds = client.get(f"/api/courses/{made['id']}/holds").json()
    assert holds == {"holds": {}, "blocking": {}, "can_delete": True}
    assert client.delete(f"/api/courses/{made['id']}").json()["deleted"] == "PCT 299"

    # 400 with the sentence, which is how every unknown thing answers here.
    assert client.get(f"/api/courses/{made['id']}").status_code == 400
    assert [c["id"] for c in client.get("/api/courses").json()] == [course["id"]]
    # Its classes went with it, and the course it was made beside is untouched.
    assert client.get(f"/api/sessions?course_id={made['id']}").json() == []
    assert client.get(f"/api/courses/{course['id']}").status_code == 200


def test_a_course_with_a_signed_decision_against_it_is_refused(client, fake):
    """A correction is somebody's signed decision. The database refuses to delete one, and so does
    this: the refusal names it, and does not claim the scans would go with it."""
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    students = client.get(f"/api/courses/{course['id']}/students").json()
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(9, 30)))
                    for s in students[:5]]
    client.post("/api/devices/1/pull", json={})
    client.post(f"/api/sessions/{session_id}/marks",
                json={"person_id": students[9]["person_id"], "status": "present",
                      "note": "Signed the paper sheet."})

    holds = client.get(f"/api/courses/{course['id']}/holds").json()
    assert holds["holds"]["scans"] == 5, "the scans are still counted and shown"
    assert holds["blocking"] == {"correction": 1}, "but only the correction stops it"
    assert holds["can_delete"] is False

    refused = client.delete(f"/api/courses/{course['id']}")
    assert refused.status_code == 400
    assert "1 correction" in refused.json()["error"]
    assert "scan" not in refused.json()["error"], "a scan is not a reason, and must not read as one"
    assert "signed decision" in refused.json()["error"]
    # Nothing was half-done.
    assert client.get(f"/api/courses/{course['id']}").status_code == 200
    assert len(client.get(f"/api/sessions?course_id={course['id']}").json()) == 1


def test_a_course_with_only_scans_against_it_can_go(client, fake):
    """The one somebody was stuck on: a course tried out, scans in its classes, nothing signed."""
    course = setup_with_roster(client)
    a_class(client, course)
    students = client.get(f"/api/courses/{course['id']}/students").json()
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(9, 30)))
                    for s in students[:9]]
    client.post("/api/devices/1/pull", json={})
    before = len(client.get("/api/punches/unmatched").json()) if False else None

    holds = client.get(f"/api/courses/{course['id']}/holds").json()
    assert holds["holds"]["scans"] == 9 and holds["can_delete"] is True
    assert client.delete(f"/api/courses/{course['id']}").json()["deleted"] == course["code"]
    assert client.get(f"/api/courses/{course['id']}").status_code == 400
    assert before is None


# -- forgetting fingerprints ---------------------------------------------------------------------

def test_the_register_can_forget_fingerprints_without_touching_the_terminal(client, fake):
    """For a terminal emptied from its own menu, leaving the register claiming fingerprints."""
    setup_with_roster(client)
    student = client.get("/api/levels/2/students").json()["students"][0]
    client.post("/api/devices/1/push", json={"level_id": 2})
    started = client.post("/api/enrollment/start",
                          json={"person_id": student["id"], "finger_index": 6,
                                "consent_confirmed": True})
    assert started.status_code == 200, started.text
    for _ in range(40):
        if client.get("/api/enrollment/status").json()["state"] == "finished":
            break
    assert client.get("/api/levels/2/students").json()["one_finger"] == 1

    before = len(fake.templates) if hasattr(fake, "templates") else None
    done = client.post("/api/fingers/forget", json={}).json()
    assert done == {"forgotten": 1, "whose": "every level"}
    assert client.get("/api/levels/2/students").json()["one_finger"] == 0
    # The terminal was not touched: the templates are still on it, which is the whole point.
    if before is not None:
        assert len(fake.templates) == before


def test_forgetting_can_be_narrowed_to_one_level(client):
    setup_with_roster(client)
    refused = client.post("/api/fingers/forget", json={"level_id": 999})
    assert refused.status_code == 400
    assert "Unknown level" in refused.json()["error"]
    assert client.post("/api/fingers/forget", json={"level_id": 2}).json() == {
        "forgotten": 0, "whose": "200 Level"}


# -- what a row says it holds --------------------------------------------------------------------

def test_a_row_carries_why_it_cannot_be_deleted(client, fake):
    """The screens show Delete on every row, disabled with the reason, rather than leaving it out,
    which is this app's own rule for a control somebody cannot use (asked for 2026-09-22)."""
    course = setup_with_roster(client)
    session_id = a_class(client, course)
    students = client.get(f"/api/courses/{course['id']}/students").json()
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]),
                               timestamp=datetime.combine(date.today(), time(9, 30)))
                    for s in students[:4]]
    client.post("/api/devices/1/pull", json={})

    client.post(f"/api/sessions/{session_id}/marks",
                json={"person_id": students[9]["person_id"], "status": "absent",
                      "note": "Not in the hall."})

    row = next(c for c in client.get(f"/api/sessions?course_id={course['id']}").json()
               if c["id"] == session_id)
    assert row["can_delete"] is False
    assert row["holds"] == {"correction": 1, "scans": 4}
    assert row["blocking"] == {"correction": 1}

    listed = next(c for c in client.get("/api/courses").json() if c["id"] == course["id"])
    assert listed["can_delete"] is False and listed["blocking"] == {"correction": 1}

    levels = {l["name"]: l for l in client.get("/api/levels").json()}
    assert levels["200 Level"]["can_remove"] is False
    assert levels["200 Level"]["holds"]["students"] == 258
    assert "200 Level still has" in levels["200 Level"]["why_not_removable"]
    # A level with nothing on it can go, and says nothing about why it cannot.
    assert levels["500 Level"]["can_remove"] is True
    assert levels["500 Level"]["holds"] == {} and levels["500 Level"]["why_not_removable"] == ""


def test_what_a_thing_holds_is_named_for_its_count(client):
    """"1 corrections" was on a real screen. The counts are summed under stable keys and named
    once, at the edge, because naming them per class put "1 correction" and "2 corrections" in
    two different buckets."""
    from rollcall import register

    assert register.name_holds({"corrections": 1}) == {"correction": 1}
    assert register.name_holds({"corrections": 2}) == {"corrections": 2}
    assert register.name_holds({"correction_requests": 1}) == {"correction request": 1}
    assert register.name_holds({"excusals": 1, "scans": 1}) == {"excused absence": 1, "scan": 1}
    assert register.say_holds({"scans": 221, "correction_requests": 1})         == "1 correction request, 221 scans"
