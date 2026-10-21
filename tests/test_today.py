"""GET /api/today: screen 4's whole contract in one shape.

The screen renders this and works nothing out for itself (docs/COMPONENT-GUIDE.md), so what is
tested here is that every figure the screen shows comes from the backend already decided.
"""
from datetime import date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from fake_zk import FakeRecord
from rollcall import today as today_module
from rollcall.app import create_app


@pytest.fixture(autouse=True)
def midday(monkeypatch):
    """Hold the clock at noon. Whether a class is upcoming or over is a question about the minute
    the screen is read, so a live clock makes these tests pass or fail by the hour they run at."""
    monkeypatch.setattr(today_module, "now",
                        lambda: datetime.combine(date.today(), time(12, 0)))


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "today.db", k40_factory=k40_factory)
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


def test_an_empty_register_says_nothing_has_been_pulled(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})
    data = client.get("/api/today").json()
    assert data["last_pull"] is None
    assert data["classes"] == []
    assert data["waiting"] == {"unassigned_classes": 0, "correction_requests": 0}
    assert data["academic_session"] == "2026/2027"


def test_a_class_today_carries_its_counts_and_its_state(client, fake):
    course = setup_with_roster(client)
    today = date.today().isoformat()
    students = client.get(f"/api/courses/{course['id']}/students").json()
    # Held this morning, so it is finished by the time anyone reads the screen.
    made = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                              "start_time": "08:00", "end_time": "10:00",
                                              "kind": "device"})
    assert made.status_code == 200, made.text
    scan_at = datetime.combine(date.today(), time(8, 5))
    fake.records = [FakeRecord(user_id=str(s["device_user_id"]), timestamp=scan_at)
                    for s in students[:5]]
    client.post("/api/devices/1/pull", json={})

    data = client.get("/api/today").json()
    row = next(c for c in data["classes"] if c["session_id"] == made.json()["id"])
    assert row["course_code"] == course["code"]
    assert row["present"] == 5
    assert row["registered"] == len(students)
    assert row["state"] == "complete"
    assert data["last_pull"]["new_count"] == 5
    assert data["last_pull"]["by"] == "Dr Lecturer"


def test_a_class_with_no_scans_is_not_the_same_as_one_still_to_come(client):
    course = setup_with_roster(client)
    today = date.today().isoformat()
    past = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                              "start_time": "08:00", "end_time": "10:00",
                                              "kind": "device"}).json()["id"]
    later = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                               "start_time": "15:00", "end_time": "17:00",
                                               "kind": "device"}).json()["id"]
    running = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                                 "start_time": "11:30", "end_time": "13:00",
                                                 "kind": "device"}).json()["id"]
    states = {c["session_id"]: c["state"] for c in client.get("/api/today").json()["classes"]}
    assert states[past] == "no_scans"
    assert states[later] == "upcoming"
    assert states[running] == "running"


def test_a_cancelled_class_says_so_and_carries_its_note(client):
    course = setup_with_roster(client)
    today = date.today().isoformat()
    session_id = client.post("/api/sessions", json={"course_id": course["id"], "date": today,
                                                    "start_time": "09:00", "end_time": "11:00",
                                                    "kind": "device"}).json()["id"]
    client.post(f"/api/sessions/{session_id}/cancel", json={"note": "Lecture hall double booked."})
    row = next(c for c in client.get("/api/today").json()["classes"] if c["session_id"] == session_id)
    assert row["state"] == "cancelled"
    assert row["cancel_note"] == "Lecture hall double booked."


def test_another_day_can_be_asked_for_and_a_bad_date_is_refused(client):
    course = setup_with_roster(client)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post("/api/sessions", json={"course_id": course["id"], "date": yesterday,
                                       "start_time": "09:00", "end_time": "11:00", "kind": "device"})
    assert client.get("/api/today").json()["classes"] == []
    assert len(client.get(f"/api/today?date={yesterday}").json()["classes"]) == 1
    assert client.get("/api/today?date=last-tuesday").status_code == 400


def test_the_rail_footer_names_the_level_when_there_is_only_one(client):
    setup_with_roster(client)
    rail = client.get("/api/rail").json()
    assert rail == {"session": True, "levels": 1, "level": "200 Level", "students": 258}


def test_the_rail_footer_counts_every_level_rather_than_the_biggest(client):
    """It used to name the biggest level and give that level's count, so a department with two
    levels imported saw one of them and a number that was not the total."""
    setup_with_roster(client)
    level = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 300)
    # Letters, not numbers, after the surname: a name with a digit in it is refused (2026-09-24).
    rows = "matric_no,name\n" + "".join(f"PCT/23/{n:04d},ADEYEMI Student {'ABCDEFG'[n - 1]}\n" for n in range(1, 8))
    preview = client.post(f"/api/levels/{level}/roster/preview",
                          files={"file": ("three hundred.csv", rows.encode(), "text/csv")})
    client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    rail = client.get("/api/rail").json()
    assert rail["students"] == 258 + 7
    assert rail["levels"] == 2
    # No single level to name once there is more than one, so the rail says the total instead.
    assert rail["level"] is None


def test_the_rail_footer_tells_no_session_apart_from_no_students(conn):
    """Both used to read "No students yet", and only one of them is fixed by importing a roster."""
    assert today_module.rail_footer(conn) == {"session": True, "levels": 0, "level": None, "students": 0}
    conn.execute("UPDATE academic_sessions SET is_current = 0")
    assert today_module.rail_footer(conn) == {"session": False, "levels": 0, "level": None, "students": 0}
