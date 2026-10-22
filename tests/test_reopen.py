"""Reopening a class taken live, for the students who had not scanned.

Asked for on 2026-10-22: "when a lecturer starts an attendance and ends it there's a possibility
that he can start the old attendance again just in case he missed some people and they couldn't do
their attendance, like reopening the attendance again for those that haven't signed to be able to
sign."

The tests move a class's first window a few minutes into the past rather than waiting, so the
gap between its End and its reopening is real minutes on the clock.
"""
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from test_live import a_course, client, fresh_terminal_memory, scan, statuses  # noqa: F401 (fixtures)
from rollcall import db, live


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def taken_and_ended(client, fake, course, scanned):
    """A class taken live four minutes ago and ended two minutes ago, with ``scanned`` in it."""
    class_id = client.post(f"/api/courses/{course['id']}/live").json()["register"]["session"]["id"]
    now = datetime.now()
    conn = db.connect(client.db_path)
    started = now - timedelta(minutes=4)
    conn.execute("UPDATE class_sessions SET opened_at = ?, start_time = ? WHERE id = ?",
                 (stamp(started), started.strftime("%H:%M"), class_id))
    conn.close()
    for student in scanned:
        scan(fake, student, now - timedelta(minutes=3))
    assert client.post(f"/api/live/{class_id}/end", json={}).status_code == 200
    conn = db.connect(client.db_path)
    ended = now - timedelta(minutes=2)
    conn.execute("UPDATE class_sessions SET closed_at = ?, end_time = ? WHERE id = ?",
                 (stamp(ended), ended.strftime("%H:%M"), class_id))
    conn.close()
    return class_id


def reopen(client, class_id):
    live._seen.clear()
    return client.post(f"/api/live/{class_id}/reopen")


def refresh(client, class_id):
    live._seen.clear()   # the next look is not throttled
    return client.post(f"/api/live/{class_id}/refresh").json()["register"]


def held(client, course):
    return next(c for c in client.get("/api/courses").json() if c["id"] == course["id"])["classes_held"]


def test_reopening_lets_whoever_had_not_scanned_scan_and_keeps_the_present_present(client, fake):
    course, students = a_course(client)
    came, missed, never = students[0], students[1], students[2]
    class_id = taken_and_ended(client, fake, course, [came])
    before = client.get(f"/api/sessions/{class_id}/register").json()
    assert statuses(before)[missed["person_id"]] == "absent"
    assert before["reopen"] == {"reason": None}, "an ended class taken today is offered for reopening"

    opened = reopen(client, class_id)
    assert opened.status_code == 200, opened.text
    assert opened.json()["register"]["open"] is True
    scan(fake, missed, datetime.now())
    during = statuses(refresh(client, class_id))
    assert during[came["person_id"]] == "present", "somebody present before the reopening lost it"
    assert during[missed["person_id"]] == "present"

    ended = client.post(f"/api/live/{class_id}/end", json={}).json()
    after = statuses(ended)
    assert after[came["person_id"]] == "present"
    assert after[missed["person_id"]] == "present", "a scan in the reopened window did not count"
    assert after[never["person_id"]] == "absent", "nobody became absent again at the second end"
    assert len(ended["windows"]) == 2 and len(ended["reopenings"]) == 1
    assert ended["reopenings"][0]["present_before"] == 1
    # The first scan of whoever was present already is still the one from the first window.
    came_row = next(s for s in ended["students"] if s["person_id"] == came["person_id"])
    assert came_row["first_scan"] < ended["reopenings"][0]["ended_at"]


def test_while_it_is_reopened_nobody_is_absent_and_it_counts_nowhere(client, fake):
    """An open class is an open class: the absent marks become "not yet" again, as at Start."""
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    assert held(client, course) == 1
    reopen(client, class_id)
    register = refresh(client, class_id)
    assert register["totals"]["absent"] == 0
    assert statuses(register)[students[1]["person_id"]] == "waiting"
    assert held(client, course) == 0, "a class taking attendance again was counted"
    assert client.get("/api/live").json()["open"]["reopened_at"]

    client.post(f"/api/live/{class_id}/end", json={})
    assert held(client, course) == 1
    assert statuses(client.get(f"/api/sessions/{class_id}/register").json())[students[1]["person_id"]] == "absent"


def test_a_scan_between_the_end_and_the_reopening_does_not_count(client, fake):
    """The minutes after the End may have been another class's, so they are in no window."""
    course, students = a_course(client)
    in_gap = students[1]
    class_id = taken_and_ended(client, fake, course, [students[0]])
    scan(fake, in_gap, datetime.now() - timedelta(minutes=1))
    reopen(client, class_id)
    ended = client.post(f"/api/live/{class_id}/end", json={}).json()
    assert statuses(ended)[in_gap["person_id"]] == "absent", "a scan made while the class was ended counted"


def test_a_scan_after_the_second_end_does_not_count(client, fake):
    course, students = a_course(client)
    late = students[1]
    class_id = taken_and_ended(client, fake, course, [students[0]])
    reopen(client, class_id)
    client.post(f"/api/live/{class_id}/end", json={})
    scan(fake, late, datetime.now() + timedelta(seconds=30))
    assert client.post("/api/devices/1/pull", json={}).status_code == 200
    register = client.get(f"/api/sessions/{class_id}/register").json()
    assert statuses(register)[late["person_id"]] == "absent", "a scan after the second End counted"
    assert register["open"] is False


def test_a_correction_made_before_reopening_still_decides(client, fake):
    """A correction is a signed decision and beats any scan, before a reopening and after it."""
    course, students = a_course(client)
    scanned_and_left, vouched_for = students[0], students[1]
    class_id = taken_and_ended(client, fake, course, [scanned_and_left])
    for student, status in ((scanned_and_left, "absent"), (vouched_for, "present")):
        marked = client.post(f"/api/sessions/{class_id}/marks", json={
            "person_id": student["person_id"], "status": status, "note": "Seen by the lecturer."})
        assert marked.status_code == 200, marked.text

    reopen(client, class_id)
    scan(fake, scanned_and_left, datetime.now())   # comes back and scans again
    during = statuses(refresh(client, class_id))
    assert during[scanned_and_left["person_id"]] == "marked_absent"
    assert during[vouched_for["person_id"]] == "marked_present"

    after = statuses(client.post(f"/api/live/{class_id}/end", json={}).json())
    assert after[scanned_and_left["person_id"]] == "marked_absent", "a scan overrode a correction"
    assert after[vouched_for["person_id"]] == "marked_present", "the second End undid a correction"
    conn = db.connect(client.db_path)
    marks = conn.execute("SELECT COUNT(*) FROM attendance_marks WHERE class_session_id = ?", (class_id,)).fetchone()[0]
    conn.close()
    assert marks == 2, "reopening wrote or removed a correction"


def test_an_excused_student_stays_excused_unless_they_scan(client, fake):
    course, students = a_course(client)
    excused, excused_but_came = students[1], students[2]
    today = datetime.now().date().isoformat()
    for student in (excused, excused_but_came):
        client.post("/api/excusals", json={"person_id": student["person_id"], "date_from": today,
                                           "date_to": today, "category": "medical", "note": "Clinic note 14."})
    class_id = taken_and_ended(client, fake, course, [students[0]])
    reopen(client, class_id)
    scan(fake, excused_but_came, datetime.now())
    after = statuses(client.post(f"/api/live/{class_id}/end", json={}).json())
    assert after[excused["person_id"]] == "excused"
    assert after[excused_but_came["person_id"]] == "present", "a scan beats an excusal, as it always has"


def test_reopening_needs_the_permission_to_correct(client, fake):
    """Its effect is a correction: absent becomes present on a class already counted."""
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    rep = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Course rep")
    client.post("/api/accounts", json={"username": "rep", "display_name": "A Rep", "password": "secret123",
                                       "role_id": rep})
    with TestClient(client.app) as theirs:
        assert theirs.post("/api/login", json={"username": "rep", "password": "secret123"}).status_code == 200
        refused = theirs.post(f"/api/live/{class_id}/reopen")
        assert refused.status_code == 403
        assert "correct attendance" in refused.json()["error"]
    assert client.get("/api/live").json()["open"] is None


def test_a_class_is_reopened_only_on_the_day_it_was_held(client, fake):
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    conn = db.connect(client.db_path)
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    conn.execute("UPDATE class_sessions SET date = ? WHERE id = ?", (yesterday, class_id))
    conn.close()
    refused = reopen(client, class_id)
    assert refused.status_code == 400
    assert "only on the day it was held" in refused.json()["error"]
    offer = client.get(f"/api/sessions/{class_id}/register").json()["reopen"]
    assert "only on the day" in offer["reason"]


def test_only_an_ended_class_taken_live_can_be_reopened(client, fake):
    course, students = a_course(client)
    today = datetime.now().date().isoformat()
    by_hand = client.post("/api/sessions", json={"course_id": course["id"], "date": today, "start_time": "00:00",
                                                 "end_time": "00:01", "kind": "manual"})
    assert by_hand.status_code == 200, by_hand.text
    by_hand_id = by_hand.json()["id"]
    assert client.get(f"/api/sessions/{by_hand_id}/register").json()["reopen"] is None
    assert "Only a class taken live" in reopen(client, by_hand_id).json()["error"]

    class_id = client.post(f"/api/courses/{course['id']}/live").json()["register"]["session"]["id"]
    assert "taking attendance already" in reopen(client, class_id).json()["error"]
    client.post(f"/api/sessions/{class_id}/cancel", json={"note": "Started by mistake."})
    assert client.get(f"/api/sessions/{class_id}/register").json()["reopen"] is None
    assert "cancelled" in reopen(client, class_id).json()["error"]


def test_one_class_at_a_time_and_enrolment_waits_while_one_is_reopened(client, fake):
    course, students = a_course(client)
    first = taken_and_ended(client, fake, course, [students[0]])
    second = client.post(f"/api/courses/{course['id']}/live").json()["register"]["session"]["id"]
    refused = reopen(client, first)
    assert refused.status_code == 400 and "End it before reopening" in refused.json()["error"]
    client.post(f"/api/live/{second}/end", json={})

    assert reopen(client, first).status_code == 200
    again = client.post(f"/api/courses/{course['id']}/live")
    assert again.status_code == 400 and "already taking attendance" in again.json()["error"]
    waits = client.post("/api/enrollment/start", json={"person_id": students[0]["person_id"],
                                                       "finger_index": 6, "consent_confirmed": True})
    assert waits.status_code == 409


def test_the_activity_log_records_the_reopening_and_the_second_end(client, fake):
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    reopen(client, class_id)
    scan(fake, students[1], datetime.now())
    client.post(f"/api/live/{class_id}/end", json={})

    entries = client.get("/api/audit").json()["entries"]
    said = [e["sentence"] for e in entries]
    reopened = next(s for s in said if s.startswith("Reopened a class for the students who had not scanned"))
    assert "with 1 of" in reopened
    ended_again = next(s for s in said if s.startswith("Ended a reopened class"))
    assert "2 present" in ended_again and "1 more present than before it was reopened" in ended_again


def test_reopenings_and_scans_stay_as_written(client, fake):
    """The database refuses to change or delete either, and a reopened class is never deleted."""
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    reopen(client, class_id)
    scan(fake, students[1], datetime.now())
    client.post(f"/api/live/{class_id}/end", json={})
    conn = db.connect(client.db_path)
    for statement in ("UPDATE class_reopenings SET reopened_at = ended_at",
                      "DELETE FROM class_reopenings",
                      "UPDATE punches SET timestamp = '2000-01-01T00:00:00'",
                      "DELETE FROM punches"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
    conn.close()
    refused = client.delete(f"/api/sessions/{class_id}")
    assert refused.status_code == 400 and "1 reopening" in refused.json()["error"]


def test_a_reopened_class_cannot_be_given_an_end_before_it_was_reopened(client, fake):
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    conn = db.connect(client.db_path)
    first_end = conn.execute("SELECT closed_at FROM class_sessions WHERE id = ?", (class_id,)).fetchone()[0]
    conn.close()
    reopen(client, class_id)
    refused = client.post(f"/api/live/{class_id}/end",
                          json={"ended_at": (datetime.fromisoformat(first_end) - timedelta(minutes=1)).strftime("%H:%M")})
    assert refused.status_code == 400 and "reopened at" in refused.json()["error"]


def test_a_level_holding_a_reopened_class_can_still_be_deleted(client, fake):
    """Deleting a roster is the one place the guards on attendance are lifted, and it takes the
    reopenings with the classes they belong to."""
    course, students = a_course(client)
    class_id = taken_and_ended(client, fake, course, [students[0]])
    reopen(client, class_id)
    client.post(f"/api/live/{class_id}/end", json={})
    level = next(l for l in client.get("/api/levels").json() if l["level_number"] == 200)
    cleared = client.post(f"/api/levels/{level['id']}/clear", json={"confirm": level["name"]})
    assert cleared.status_code == 200, cleared.text
    conn = db.connect(client.db_path)
    left = conn.execute("SELECT COUNT(*) FROM class_reopenings").fetchone()[0]
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    conn.close()
    assert left == 0
    assert "reopenings_immutable_delete" in triggers, "the guard did not come back"
