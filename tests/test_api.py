from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from conftest import ROSTER
from fake_zk import FakeRecord
from rollcall import enrollment
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "api.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def setup_lecturer(client):
    r = client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                         "password": "secret123", "academic_session": "2026/2027"})
    assert r.status_code == 200, r.text
    return r


def level_id(client, number):
    return next(l["id"] for l in client.get("/api/levels").json() if l["level_number"] == number)


def import_roster(client, number=200, text=None):
    content = text.encode() if text else ROSTER.read_bytes()
    preview = client.post(f"/api/levels/{level_id(client, number)}/roster/preview",
                          files={"file": ("roster.csv", content, "text/csv")})
    assert preview.status_code == 200, preview.text
    commit = client.post(f"/api/roster-imports/{preview.json()['import_id']}/commit")
    assert commit.status_code == 200, commit.text
    return preview.json(), commit.json()


def test_setup_once_and_login_required(client):
    assert client.get("/api/setup/status").json()["needs_setup"] is True
    assert client.get("/api/levels").status_code == 401
    setup_lecturer(client)
    assert client.get("/api/me").json()["role"] == "Lecturer"
    assert client.post("/api/setup", json={"username": "x", "display_name": "x", "password": "secret123",
                                            "academic_session": "2026/2027"}).status_code == 409
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"username": "lecturer", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "lecturer", "password": "secret123"}).status_code == 200


def role_id(client, name):
    return next(r["id"] for r in client.get("/api/roles").json() if r["name"] == name)


def test_viewer_cannot_change_device_or_roster(client):
    setup_lecturer(client)
    assert client.post("/api/accounts", json={"username": "assistant", "display_name": "TA",
                                               "password": "secret123",
                                               "role_id": role_id(client, "Viewer")}).status_code == 200
    client.post("/api/logout")
    client.post("/api/login", json={"username": "assistant", "password": "secret123"})
    assert client.post("/api/devices/1/clear-attendance", json={"confirm_serial": "x"}).status_code == 403
    assert client.post("/api/devices/1/unlock-menu", json={"confirm_serial": "x"}).status_code == 403
    assert client.post("/api/enrollment/start", json={"person_id": 1, "finger_index": 0}).status_code == 403
    # The seeded Viewer has no register.pull. A course rep does, which is the point of the two roles.
    assert client.post("/api/devices/1/pull").status_code == 403


def test_a_course_rep_can_pull_but_not_correct(client):
    setup_lecturer(client)
    assert client.post("/api/accounts", json={"username": "rep", "display_name": "Rep",
                                               "password": "secret123",
                                               "role_id": role_id(client, "Course rep")}).status_code == 200
    client.post("/api/logout")
    client.post("/api/login", json={"username": "rep", "password": "secret123"})
    assert client.post("/api/devices/1/pull").status_code == 200
    r = client.post("/api/sessions/1/marks", json={"person_id": 1, "status": "present", "note": "x"})
    assert r.status_code == 403
    assert "correct attendance" in r.json()["error"].lower()


def test_other_host_header_is_rejected(client):
    assert client.get("/api/setup/status", headers={"host": "evil.example"}).status_code == 400


def test_lecturer_super_admin_needs_password_and_pushes(client, fake):
    setup_lecturer(client)
    r = client.post("/api/staff", json={"surname": "LECTURER", "other_names": "Name", "device_user_id": 1,
                                         "super_admin": True})
    assert r.status_code == 400
    r = client.post("/api/staff", json={"surname": "LECTURER", "other_names": "Name", "device_user_id": 1,
                                         "super_admin": True, "password": "4321"})
    person_id = r.json()["person_id"]
    # Saved but not pushed, so the terminal still has no Super Admin.
    roles = client.get("/api/devices/1/roles").json()
    assert any("No Super Admin" in w for w in roles["warnings"])
    assert client.post("/api/devices/1/push", json={"person_ids": [person_id]}).status_code == 200
    assert fake.users[1].privilege == 14
    roles = client.get("/api/devices/1/roles").json()
    assert any("Only one Super Admin" in w for w in roles["warnings"])
    unlock = client.post("/api/devices/1/unlock-menu", json={"confirm_serial": "FDDW250226081"}).json()
    assert unlock["demoted_user_ids"] == ["1"]
    assert fake.users[1].privilege == 0


def test_full_register_flow(client, fake):
    setup_lecturer(client)
    preview, commit = import_roster(client)
    assert preview["id_range"] == [2001, 2258]
    assert commit["new"] == 258

    lvl = level_id(client, 200)
    push = client.post("/api/devices/1/push", json={"level_id": lvl})
    assert push.json()["pushed"] == 258 and len(fake.users) == 258

    students = client.get(f"/api/levels/{lvl}/students").json()
    first = students["students"][0]
    assert first["device_user_id"] == 2001
    # The first of the two fingers a student gives, in ZKTeco's own numbering.
    assert first["next_finger"] == enrollment.TWO_FINGERS[0] == 6

    one, two = enrollment.TWO_FINGERS
    no_consent = client.post("/api/enrollment/start", json={"person_id": first["id"], "finger_index": one})
    assert no_consent.status_code == 400
    start = client.post("/api/enrollment/start",
                        json={"person_id": first["id"], "finger_index": one, "consent_confirmed": True})
    assert start.status_code == 200, start.text
    client.app_ref.state.enrollment.wait(5)
    status = client.get("/api/enrollment/status").json()
    assert status["outcome"] == "captured" and status["fingers_after"] == [one]
    assert client.get(f"/api/levels/{lvl}/students").json()["students"][0]["next_finger"] == two

    fake.records = [
        FakeRecord("2001", datetime(2026, 9, 15, 9, 14, 23)),
        FakeRecord("2001", datetime(2026, 9, 15, 10, 58, 2)),
        FakeRecord("2003", datetime(2026, 9, 15, 11, 5, 0)),
        FakeRecord("9999", datetime(2026, 9, 15, 11, 6, 0)),
        FakeRecord("2004", datetime(2026, 9, 15, 14, 0, 0)),
    ]
    first_pull = client.post("/api/devices/1/pull").json()
    assert first_pull["new"] == 5
    second_pull = client.post("/api/devices/1/pull").json()
    assert second_pull["new"] == 0 and second_pull["already_known"] == 5
    assert [u["device_user_id"] for u in client.get("/api/punches/unmatched").json()] == ["9999"]

    # An import makes no course (2026-09-24): the lecturer makes it, and it takes the whole level.
    course = client.post("/api/courses", json={"level_id": lvl, "code": "PCT 201"}).json()["id"]
    suggest = client.get("/api/sessions/suggest", params={"course_id": course, "day": "2026-09-15"}).json()
    assert suggest["start_time"] == "09:14"

    session = client.post("/api/sessions", json={"course_id": course, "date": "2026-09-15", "start_time": "09:00",
                                                  "end_time": "11:00", "course_code": "PCT 201"}).json()
    reg = client.get(f"/api/sessions/{session['id']}/register").json()
    assert reg["totals"]["students"] == 258
    assert reg["totals"]["present"] == 2          # 2001 and 2003 (11:05 is inside the 30 minute grace)
    by_id = {s["device_user_id"]: s for s in reg["students"]}
    assert by_id[2004]["status"] == "absent"

    person_2004 = by_id[2004]["person_id"]
    assert client.post(f"/api/sessions/{session['id']}/marks",
                       json={"person_id": person_2004, "status": "present", "note": ""}).status_code == 400
    assert client.post(f"/api/sessions/{session['id']}/marks",
                       json={"person_id": person_2004, "status": "present",
                             "note": "Scanner queue, seen in class"}).status_code == 200
    reg = client.get(f"/api/sessions/{session['id']}/register").json()
    assert reg["totals"]["present"] == 3
    assert {s["device_user_id"]: s for s in reg["students"]}[2004]["status"] == "marked_present"

    summary = client.get(f"/api/courses/{course}/summary").json()
    assert summary["sessions_held"] == 1
    assert summary["below_threshold"] == 255

    assert client.post("/api/devices/1/clear-attendance", json={"confirm_serial": "wrong"}).status_code == 400
    assert len(fake.records) == 5
    cleared = client.post("/api/devices/1/clear-attendance", json={"confirm_serial": "FDDW250226081"})
    assert cleared.status_code == 200, cleared.text
    assert fake.records == []
    reg_after = client.get(f"/api/sessions/{session['id']}/register").json()
    assert reg_after["totals"]["present"] == 3

    actions = [a["action"] for a in client.get("/api/audit").json()["entries"]]
    assert "device.clear_attendance" in actions and "attendance.mark" in actions


def test_wrong_device_on_cable_is_refused(client, fake):
    setup_lecturer(client)
    client.post("/api/devices/1/pull")
    fake.serial = "SOMEOTHERSERIAL"
    r = client.post("/api/devices/1/pull")
    assert r.status_code == 502 and r.json()["code"] == "wrong_device"


def test_push_blocked_when_over_capacity(client, fake):
    setup_lecturer(client)
    import_roster(client)
    fake.user_capacity = 100
    r = client.post("/api/devices/1/push", json={"level_id": level_id(client, 200)})
    assert r.status_code == 400 and "holds 100" in r.json()["error"]
    assert fake.users == {}


def test_unreachable_device_is_a_named_error(client, fake):
    setup_lecturer(client)
    fake.reachable = False
    r = client.get("/api/devices/1/status")
    assert r.status_code == 502 and r.json()["code"] == "unreachable"


def test_usb_import_waits_for_a_real_file(client):
    setup_lecturer(client)
    assert client.post("/api/imports/usb").status_code == 501


def test_backup_download(client):
    setup_lecturer(client)
    r = client.get("/api/backup")
    assert r.status_code == 200 and r.content[:15] == b"SQLite format 3"
