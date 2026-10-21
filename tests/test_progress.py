"""Where students stand part way through: the notice to post, and the lecturer's at-risk list."""
import io
from datetime import datetime

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from conftest import ROSTER
from rollcall import courses, db, progress, register, roster
from rollcall.app import create_app
from rollcall.device import RawPunch
from rollcall.punches import store_punches

L200 = ("matric_no,name,level\n"
        "A/1,ALPHA Ada,200\nA/2,BRAVO Bola,200\nA/3,CHARLIE Chidi,200\nA/4,DELTA Dayo,200\n")


def build(conn):
    """Four classes held of ten planned, with each student attending a different number."""
    level = conn.execute("SELECT id FROM levels WHERE level_number = 200").fetchone()["id"]
    import_id = conn.execute(
        "INSERT INTO roster_imports(level_id, academic_session_id, device_id, csv_text, status, created_at)"
        " VALUES (?, 1, 1, ?, 'pending', ?)", (level, L200, db.now())).lastrowid
    roster.commit(conn, import_id, 1)
    course = courses.create_course(conn, 1, level, "200 Level", None, 1)
    register.save_plan(conn, course, 1, None, None, 10, 75)
    for day in range(4):
        register.create_session(conn, course, f"2026-09-{14 + day:02d}", "09:00", "11:00", "device", 1)
    attendance = {"A/1": 4, "A/2": 3, "A/3": 1, "A/4": 0}
    for matric, times in attendance.items():
        who = conn.execute("SELECT device_user_id FROM people WHERE matric_no = ?", (matric,)).fetchone()[0]
        for day in range(times):
            store_punches(conn, 1, [RawPunch(str(who), datetime(2026, 9, 14 + day, 10, 55), 1, 255)],
                          "network", 1)
    return course


def row(data, matric):
    return next(r for r in data["students"] if r["matric_no"] == matric)


def test_progress_says_what_each_student_still_needs(conn):
    course = build(conn)
    data = progress.progress(conn, course)

    # Ada has all four; she needs 8 of 10 in the end, so 4 more of the 6 left.
    assert (row(data, "A/1")["percent"], row(data, "A/1")["status"]) == (100.0, "on_track")
    assert row(data, "A/1")["more_needed"] == 4 and row(data, "A/1")["can_still_miss"] == 2
    # Chidi has 1 of 4: still reachable, 7 more needed of 6 left is impossible, so he cannot reach it.
    assert row(data, "A/3")["status"] == "cannot_reach"
    assert row(data, "A/3")["best_possible_percent"] == 70.0      # 1 + 6 of 10
    assert row(data, "A/4")["status"] == "cannot_reach"
    assert data["rules"]["classes_remaining"] == 6 and data["rules"]["threshold_percent"] == 75
    # Bola has 3 of 4, exactly the pass mark, so she is not on the at-risk list.
    assert row(data, "A/2")["status"] == "on_track"
    assert data["counts"]["at_risk_list"] == 2 and data["counts"]["cannot_reach"] == 2


def test_the_at_risk_list_leaves_out_students_who_are_fine(conn):
    course = build(conn)
    data = progress.progress(conn, course)
    listed = [r["matric_no"] for r in progress.rows_for(data, "at_risk")]
    assert listed == ["A/3", "A/4"] and "A/1" not in listed
    assert [r["matric_no"] for r in progress.rows_for(data, "notice")] == ["A/1", "A/2", "A/3", "A/4"]


def test_the_notice_carries_no_names_because_it_is_posted_in_public(conn):
    course = build(conn)
    data = progress.progress(conn, course)
    notice = progress.to_xlsx(data, "notice")
    values = [c.value for r in load_workbook(io.BytesIO(notice)).active.iter_rows() for c in r if c.value]
    assert "MATRIC NO." in values and "A/3" in values
    assert not any(isinstance(v, str) and "ALPHA" in v for v in values)
    assert any(isinstance(v, str) and v.startswith("ATTENDANCE SO FAR") for v in values)

    at_risk = progress.to_xlsx(data, "at_risk")
    names = [c.value for r in load_workbook(io.BytesIO(at_risk)).active.iter_rows() for c in r if c.value]
    assert any(isinstance(v, str) and "CHARLIE Chidi" in v for v in names)   # the lecturer's copy names them


def test_both_lists_export_as_pdf(conn):
    course = build(conn)
    data = progress.progress(conn, course)
    for variant in progress.VARIANTS:
        content = progress.to_pdf(data, variant, "a4")
        assert content[:5] == b"%PDF-"
        assert b"/MediaBox [ 0 0 595.27" in content
    assert progress.filename(data, "pdf", "notice").startswith("200-Level-attendance-so-far-")
    assert progress.filename(data, "xlsx", "at_risk").endswith(".xlsx")


def test_progress_api_and_exports(tmp_path, k40_factory):
    with TestClient(create_app(tmp_path / "p.db", k40_factory=k40_factory)) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr", "password": "secret123",
                                   "academic_session": "2026/2027"})
        level = next(l["id"] for l in c.get("/api/levels").json() if l["level_number"] == 200)
        preview = c.post(f"/api/levels/{level}/roster/preview", files={"file": ("r.csv", ROSTER.read_bytes())}).json()
        c.post(f"/api/roster-imports/{preview['import_id']}/commit")
        course = c.post("/api/courses", json={"level_id": level, "code": "200 Level"}).json()["id"]

        data = c.get(f"/api/courses/{course}/progress").json()
        assert data["counts"]["total"] == 258 and data["rules"]["threshold_percent"] == 75
        # No class held yet, so everyone can still reach the pass mark.
        assert data["students"][0]["status"] == "on_track" and data["students"][0]["percent"] == 0.0

        pdf = c.get(f"/api/courses/{course}/progress/export", params={"variant": "notice"})
        assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
        assert "attendance-so-far" in pdf.headers["content-disposition"]
        xlsx = c.get(f"/api/courses/{course}/progress/export", params={"variant": "at_risk", "format": "xlsx"})
        assert xlsx.status_code == 200 and "at-risk" in xlsx.headers["content-disposition"]
        assert c.get(f"/api/courses/{course}/progress/export", params={"variant": "everyone"}).status_code == 422
