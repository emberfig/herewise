from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from rollcall import courses, db, register, reminders, roster
from rollcall.app import create_app
from rollcall.device import RawPunch
from rollcall.punches import store_punches

FOUR_STUDENTS = ("matric_no,name,level\n"
                 "A/1,ALPHA Student,200\nA/2,BRAVO Student,200\nA/3,CHARLIE Student,200\nA/4,DELTA Student,200\n")


# -- reminders ---------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, k40_factory):
    with TestClient(create_app(tmp_path / "r.db", k40_factory=k40_factory)) as c:
        r = c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                        "password": "secret123", "academic_session": "2026/2027"})
        assert r.status_code == 200
        yield c


def keys(client):
    return {r["key"]: r for r in client.get("/api/reminders").json()}


def add_lecturer_admin(client):
    r = client.post("/api/staff", json={"surname": "LECTURER", "other_names": "Name", "device_user_id": 1,
                                         "super_admin": True, "password": "4321"})
    person_id = r.json()["person_id"]
    assert client.post("/api/devices/1/push", json={"person_ids": [person_id]}).status_code == 200
    return person_id


def test_no_super_admin_can_be_put_off_but_not_cancelled(client):
    me = client.get("/api/me").json()
    assert [r["key"] for r in me["reminders"]] == ["first_super_admin:1"]
    assert me["reminders"][0]["can_cancel"] is False
    assert client.post("/api/reminders/first_super_admin:1/cancel").status_code == 400
    assert client.post("/api/reminders/first_super_admin:1/remind-later", json={"days": 1}).status_code == 200
    assert keys(client) == {}
    client.post("/api/reminders/first_super_admin:1/restore")
    assert "first_super_admin:1" in keys(client)


def test_second_super_admin_reminder_later_cancel_and_restore(client, tmp_path):
    add_lecturer_admin(client)
    reminder = keys(client)["second_super_admin:1"]
    assert reminder["can_cancel"] is True
    assert reminder["actions"] == ["choose", "remind_later", "cancel"]

    # Remind me later hides it until the date passes.
    later = client.post("/api/reminders/second_super_admin:1/remind-later", json={}).json()
    assert datetime.fromisoformat(later["remind_after"]) > datetime.now() + timedelta(days=6)
    assert keys(client) == {}
    conn = db.connect(tmp_path / "r.db")
    conn.execute("UPDATE reminders SET snoozed_until = ? WHERE key = 'second_super_admin:1'",
                 ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),))
    assert "second_super_admin:1" in keys(client)

    # Cancel hides it for good, and restore brings it back.
    assert client.post("/api/reminders/second_super_admin:1/cancel").json()["cancelled"] is True
    assert keys(client) == {}
    assert client.get("/api/me").json()["reminders"] == []
    client.post("/api/reminders/second_super_admin:1/restore")
    assert "second_super_admin:1" in keys(client)
    conn.close()


def test_lecturer_chooses_a_student_as_second_admin(client, fake):
    add_lecturer_admin(client)
    lvl = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 200)
    preview = client.post(f"/api/levels/{lvl}/roster/preview", files={"file": ("r.csv", FOUR_STUDENTS.encode())}).json()
    client.post(f"/api/roster-imports/{preview['import_id']}/commit")
    client.post("/api/devices/1/push", json={"level_id": lvl})
    client.post("/api/reminders/second_super_admin:1/cancel")

    candidates = client.get("/api/devices/1/admin-candidates").json()
    assert candidates["current_admins"] == 1
    assert candidates["people"][0]["role"] == "staff"
    student = next(p for p in candidates["people"] if p["device_user_id"] == 2001)
    assert "warning" in student

    r = client.post(f"/api/people/{student['id']}/device-role", json={"super_admin": True, "password": "1111"})
    assert r.status_code == 400 and "student" in r.json()["error"]
    r = client.post(f"/api/people/{student['id']}/device-role",
                    json={"super_admin": True, "password": "1111", "confirm_student": True})
    assert r.status_code == 200 and r.json()["super_admins_on_device"] == 2
    assert fake.users[2001].privilege == 14
    assert keys(client) == {}

    # Losing the second admin raises the reminder again, even though it was cancelled before.
    r = client.post(f"/api/people/{student['id']}/device-role", json={"super_admin": False})
    assert r.json()["super_admins_on_device"] == 1 and "second" in r.json()["warning"]
    assert "second_super_admin:1" in keys(client)



def person_row(tmp_path, person_id):
    conn = db.connect(tmp_path / "r.db")
    row = dict(conn.execute("SELECT device_privilege, device_password, password_reason FROM people WHERE id = ?",
                            (person_id,)).fetchone())
    conn.close()
    return row


def test_failed_push_keeps_the_super_admin_change_unsaved(client, fake, tmp_path):
    r = client.post("/api/staff", json={"surname": "LECTURER", "other_names": "Name", "device_user_id": 1,
                                         "super_admin": False, "password": "4321"})
    person_id = r.json()["person_id"]
    before = person_row(tmp_path, person_id)
    assert "first_super_admin:1" in keys(client)

    fake.reachable = False
    r = client.post(f"/api/people/{person_id}/device-role", json={"super_admin": True, "password": "4321"})
    assert r.status_code == 502 and r.json()["code"] == "unreachable"
    assert person_row(tmp_path, person_id) == before
    assert before["device_privilege"] == 0
    # The reminder that cannot be cancelled stays, because the terminal is still unprotected.
    assert set(keys(client)) == {"first_super_admin:1"}
    assert keys(client)["first_super_admin:1"]["can_cancel"] is False

    fake.reachable = True
    r = client.post(f"/api/people/{person_id}/device-role", json={"super_admin": True, "password": "4321"})
    assert r.status_code == 200
    assert person_row(tmp_path, person_id)["device_privilege"] == 14 and fake.users[1].privilege == 14
    assert set(keys(client)) == {"second_super_admin:1"}


def test_failed_push_keeps_the_fallback_password_unsaved(client, fake, tmp_path):
    lvl = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 200)
    preview = client.post(f"/api/levels/{lvl}/roster/preview", files={"file": ("r.csv", FOUR_STUDENTS.encode())}).json()
    client.post(f"/api/roster-imports/{preview['import_id']}/commit")
    student = next(s for s in client.get(f"/api/levels/{lvl}/students").json()["students"]
                   if s["device_user_id"] == 2001)
    before = person_row(tmp_path, student["id"])
    body = {"password": "2468", "reason": "No readable fingerprint"}

    fake.reachable = False
    r = client.post(f"/api/people/{student['id']}/fallback-password", json=body)
    assert r.status_code == 502 and r.json()["code"] == "unreachable"
    assert person_row(tmp_path, student["id"]) == before
    assert before["device_password"] is None
    after = next(s for s in client.get(f"/api/levels/{lvl}/students").json()["students"] if s["id"] == student["id"])
    assert after["complete"] is False

    fake.reachable = True
    assert client.post(f"/api/people/{student['id']}/fallback-password", json=body).status_code == 200
    assert person_row(tmp_path, student["id"])["device_password"] == "2468"
    assert fake.users[2001].password == "2468"


def test_super_admin_not_yet_pushed_does_not_count(client, fake):
    r = client.post("/api/staff", json={"surname": "LECTURER", "other_names": "Name", "device_user_id": 1,
                                         "password": "4321"})
    assert r.status_code == 200
    assert fake.users == {}

    # Saved as a Super Admin but not on the terminal: the reminder that cannot be cancelled stays.
    assert set(keys(client)) == {"first_super_admin:1"}
    assert keys(client)["first_super_admin:1"]["can_cancel"] is False
    candidates = client.get("/api/devices/1/admin-candidates").json()
    assert candidates["current_admins"] == 0
    assert candidates["people"][0]["is_super_admin"] is False
    assert candidates["people"][0]["awaiting_push"] is True
    roles = client.get("/api/devices/1/roles").json()
    assert roles["admins"] == [] and "No Super Admin" in roles["warnings"][0]

    # Once pushed, the same person counts.
    assert client.post("/api/devices/1/push", json={"person_ids": [r.json()["person_id"]]}).status_code == 200
    assert fake.users[1].privilege == 14
    assert set(keys(client)) == {"second_super_admin:1"}
    candidates = client.get("/api/devices/1/admin-candidates").json()
    assert candidates["current_admins"] == 1 and candidates["people"][0]["awaiting_push"] is False
    assert len(client.get("/api/devices/1/roles").json()["admins"]) == 1


def test_device_role_counts_only_admins_on_the_terminal(client, fake):
    add_lecturer_admin(client)
    r = client.post("/api/staff", json={"surname": "SECOND", "other_names": "Staff", "device_user_id": 2,
                                         "password": "5555"})
    assert 2 not in fake.users
    third = client.post("/api/staff", json={"surname": "THIRD", "other_names": "Staff", "device_user_id": 3,
                                               "super_admin": False}).json()["person_id"]
    r = client.post(f"/api/people/{third}/device-role", json={"super_admin": False})
    assert r.status_code == 200
    assert r.json()["super_admins_on_device"] == 1 and "second" in r.json()["warning"]


def unlock(client, serial="FDDW250226081"):
    return client.post("/api/devices/1/unlock-menu", json={"confirm_serial": serial})


def test_unlock_makes_the_database_agree_with_the_terminal(client, fake, tmp_path):
    person_id = add_lecturer_admin(client)
    assert set(keys(client)) == {"second_super_admin:1"}

    r = unlock(client)
    assert r.status_code == 200 and r.json()["demoted_user_ids"] == ["1"]
    assert fake.users[1].privilege == 0
    row = person_row(tmp_path, person_id)
    assert row["device_privilege"] == 0
    assert row["device_password"] == "4321"
    conn = db.connect(tmp_path / "r.db")
    assert reminders.count_admins(conn, 1) == 0
    conn.close()
    # The terminal is open to anyone, so the reminder that cannot be cancelled is back.
    assert set(keys(client)) == {"first_super_admin:1"}
    assert keys(client)["first_super_admin:1"]["can_cancel"] is False


def test_unlock_refuses_a_different_terminal(client, fake, tmp_path):
    person_id = add_lecturer_admin(client)   # the push records FDDW250226081 as this device's serial
    fake.serial = "OTHER0000000"

    r = unlock(client)
    assert r.status_code == 502 and r.json()["code"] == "wrong_device"
    assert fake.users[1].privilege == 14
    assert person_row(tmp_path, person_id)["device_privilege"] == 14
    assert set(keys(client)) == {"second_super_admin:1"}


def test_unlock_needs_the_serial_typed_exactly(client, fake, tmp_path):
    person_id = add_lecturer_admin(client)
    assert client.post("/api/devices/1/unlock-menu").status_code == 422

    r = unlock(client, "FDDW25022608")
    assert r.status_code == 400 and "serial" in r.json()["error"]
    assert fake.users[1].privilege == 14
    assert person_row(tmp_path, person_id)["device_privilege"] == 14
    assert set(keys(client)) == {"second_super_admin:1"}

    assert unlock(client, "  FDDW250226081 ").status_code == 200
    assert fake.users[1].privilege == 0


# -- attendance percentages --------------------------------------------------------------------

def build_level(conn, attendance: dict[str, int], sessions: int = 4):
    """Four students, `sessions` classes on consecutive days, each student present for the count given."""
    lvl = conn.execute("SELECT id FROM levels WHERE level_number = 200").fetchone()["id"]
    import_id = conn.execute(
        "INSERT INTO roster_imports(level_id, academic_session_id, device_id, csv_text, status, created_at)"
        " VALUES (?, 1, 1, ?, 'pending', ?)", (lvl, FOUR_STUDENTS, db.now())).lastrowid
    roster.commit(conn, import_id, 1)
    course = courses.create_course(conn, 1, lvl, "200 Level", None, 1)
    ids = {m: conn.execute("SELECT device_user_id FROM people WHERE matric_no = ?", (m,)).fetchone()[0]
           for m in attendance}
    records = []
    for day in range(sessions):
        date = f"2026-09-{14 + day:02d}"
        register.create_session(conn, course, date, "09:00", "11:00", "device", 1)
        for matric, count in attendance.items():
            if day < count:
                records.append(RawPunch(str(ids[matric]), datetime.fromisoformat(f"{date}T10:55:00"), 1, 255))
    store_punches(conn, 1, records, "network", 1)
    return course


def by_matric(summary):
    return {s["matric_no"]: s for s in summary["students"]}


def test_weeks_and_classes_per_week_drive_what_each_student_needs(conn):
    lvl = build_level(conn, {"A/1": 4, "A/2": 2, "A/3": 1, "A/4": 0})
    summary = register.course_summary(conn, lvl, threshold_percent=75, weeks=5, classes_per_week=2)
    assert summary["planned_classes"] == 10
    assert summary["classes_needed_to_pass"] == 8       # 75% of 10 is 7.5, so 8 classes
    assert summary["classes_remaining"] == 6
    s = by_matric(summary)
    assert (s["A/1"]["percent"], s["A/1"]["more_needed"], s["A/1"]["can_still_miss"], s["A/1"]["status"]) == \
        (100.0, 4, 2, "on_track")
    assert (s["A/2"]["percent"], s["A/2"]["more_needed"], s["A/2"]["can_still_miss"], s["A/2"]["status"]) == \
        (50.0, 6, 0, "at_risk")
    assert (s["A/3"]["best_possible_percent"], s["A/3"]["status"]) == (70.0, "cannot_reach")
    assert s["A/4"]["status"] == "cannot_reach"
    assert summary["below_threshold"] == 3
    assert summary["status_counts"] == {"on_track": 1, "at_risk": 1, "cannot_reach": 2}


def test_total_classes_and_met(conn):
    lvl = build_level(conn, {"A/1": 4, "A/2": 3, "A/3": 2, "A/4": 0})
    s = by_matric(register.course_summary(conn, lvl, threshold_percent=75, total_classes=4))
    assert s["A/1"]["status"] == "met" and s["A/2"]["status"] == "met"   # 3 of 4 is exactly 75%
    assert s["A/3"]["status"] == "cannot_reach"


def drop_templates(conn):
    """Imports now create a sheet template, which is itself a plan. Remove it to test the no-plan path."""
    conn.execute("DELETE FROM register_weeks")
    conn.execute("DELETE FROM register_templates")


def test_without_a_plan_it_is_percentage_so_far(conn):
    lvl = build_level(conn, {"A/1": 4, "A/2": 3, "A/3": 2, "A/4": 0})
    drop_templates(conn)
    summary = register.course_summary(conn, lvl)
    s = by_matric(summary)
    assert summary["threshold_percent"] == 75 and summary["plan"]["threshold_source"] == "setting"
    assert (s["A/2"]["percent"], s["A/2"]["status"]) == (75.0, "on_track")
    assert (s["A/3"]["percent"], s["A/3"]["status"]) == (50.0, "below")
    assert s["A/1"]["more_needed"] is None


def test_every_student_is_listed_before_any_class(conn):
    lvl = build_level(conn, {"A/1": 0}, sessions=0)
    summary = register.course_summary(conn, lvl)
    assert len(summary["students"]) == 4
    assert {s["status"] for s in summary["students"]} == {"on_track"}      # 12 classes still to come
    drop_templates(conn)
    summary = register.course_summary(conn, lvl)
    assert {s["status"] for s in summary["students"]} == {"no_classes_yet"}


def test_more_classes_held_than_planned_is_flagged(conn):
    lvl = build_level(conn, {"A/1": 4})
    summary = register.course_summary(conn, lvl, total_classes=3)
    assert summary["warnings"] and summary["classes_remaining"] == 0


def test_plan_validation(conn):
    lvl = build_level(conn, {"A/1": 1}, sessions=1)
    with pytest.raises(register.RegisterError):
        register.course_summary(conn, lvl, weeks=10)
    with pytest.raises(register.RegisterError):
        register.save_plan(conn, lvl, 1, None, None, None, 0)
    with pytest.raises(register.RegisterError):
        register.save_plan(conn, lvl, 1, 60, 2, None, 75)


def test_saved_plan_is_used_and_what_if_is_not_saved(client):
    level = next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == 200)
    lvl = client.post("/api/courses", json={"level_id": level, "code": "PCT 201"}).json()["id"]
    r = client.put(f"/api/courses/{lvl}/attendance-plan", json={"weeks": 13, "classes_per_week": 2,
                                                               "threshold_percent": 70})
    assert r.status_code == 200 and r.json()["saved"]["weeks"] == 13
    summary = client.get(f"/api/courses/{lvl}/summary").json()
    assert summary["planned_classes"] == 26 and summary["threshold_percent"] == 70
    assert summary["classes_needed_to_pass"] == 19    # 70% of 26 is 18.2
    what_if = client.get(f"/api/courses/{lvl}/summary", params={"threshold_percent": 80, "total_classes": 20}).json()
    assert what_if["classes_needed_to_pass"] == 16 and what_if["plan"]["uses_overrides"]
    assert client.get(f"/api/courses/{lvl}/attendance-plan").json()["saved"]["threshold_percent"] == 70
    assert client.put(f"/api/courses/{lvl}/attendance-plan", json={"weeks": 13}).status_code == 400


def test_migration_from_version_1_keeps_data(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    db.initialise(conn, target=1)
    conn.execute("INSERT INTO settings(key, value) VALUES ('attendance_threshold_percent', '80')"
                 " ON CONFLICT(key) DO UPDATE SET value = '80'")
    conn.execute("INSERT INTO settings(key, value) VALUES ('grace_before_minutes', '20')"
                 " ON CONFLICT(key) DO UPDATE SET value = '20'")
    db.initialise(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert db.get_setting(conn, "attendance_threshold_percent") == "80"
    # Taken off the Settings screen in schema 12: the row goes, and the value is fixed in the code.
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key = 'grace_before_minutes'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM attendance_plans").fetchone()[0] == 0
    conn.close()
