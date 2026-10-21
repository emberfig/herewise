"""Roles people create and name, and the correction requests that go with them.

The two invariants under test are the ones that cannot be granted away: the database always keeps an
enabled owner, and nobody corrects their own attendance whatever their role says.
"""
import sqlite3

import pytest

from rollcall import auth, db, register, roles
from test_api import client, role_id, setup_lecturer  # noqa: F401


def owner(conn):
    return roles.owner_role_id(conn)


def account(conn, username, role_id_, person_id=None):
    return auth.create_account(conn, username, username.title(), "secret123", role_id_, person_id)


# -- roles are rows people name -------------------------------------------------------------------

def test_a_role_can_be_created_named_edited_and_deleted(conn):
    lecturer = 1
    role_id_ = roles.create_role(conn, "Lab demonstrator", "Runs the practical",
                                 ["register.read", "register.pull"], lecturer)
    assert roles.permissions_of_role(conn, role_id_) == {"register.read", "register.pull"}

    roles.update_role(conn, role_id_, lecturer, name="Practical lead",
                      permissions=["register.read", "register.request", "students.read"])
    role = roles.get_role(conn, role_id_)
    assert role["name"] == "Practical lead"
    assert roles.permissions_of_role(conn, role_id_) == {"register.read", "register.request", "students.read"}

    roles.delete_role(conn, role_id_, lecturer)
    with pytest.raises(roles.RoleError):
        roles.get_role(conn, role_id_)


def test_a_role_carries_exactly_what_was_ticked(conn):
    role_id_ = roles.create_role(conn, "Marker", "", ["register.correct"], 1)
    person = account(conn, "marker", role_id_)
    assert roles.has(conn, person, "register.correct")
    assert not roles.has(conn, person, "register.read")
    assert not roles.has(conn, person, "device.manage")


def test_a_permission_the_app_does_not_have_is_refused(conn):
    with pytest.raises(roles.RoleError) as exc:
        roles.create_role(conn, "Everything", "", ["register.read", "register.delete_everything"], 1)
    assert "register.delete_everything" in str(exc.value)


def test_two_roles_cannot_share_a_name(conn):
    roles.create_role(conn, "Course rep 2", "", [], 1)
    with pytest.raises(roles.RoleError):
        roles.create_role(conn, "course rep 2", "", [], 1)


def test_a_role_in_use_cannot_be_deleted(conn):
    role_id_ = roles.create_role(conn, "Demonstrator", "", ["register.read"], 1)
    account(conn, "demo", role_id_)
    with pytest.raises(roles.RoleError) as exc:
        roles.delete_role(conn, role_id_, 1)
    assert "Move them to another role first" in str(exc.value)


# -- the owner role --------------------------------------------------------------------------------

def test_the_owner_role_holds_every_permission_including_new_ones(conn):
    lecturer = conn.execute("SELECT * FROM accounts WHERE username = 'lecturer'").fetchone()
    assert roles.permissions_for(conn, lecturer) == roles.ALL_PERMISSIONS
    # Nothing was written into role_permissions for it: the answer is computed, so a permission added
    # in a later version cannot leave the owner locked out of a feature only they can grant.
    stored = conn.execute("SELECT COUNT(*) FROM role_permissions WHERE role_id = ?", (owner(conn),)).fetchone()[0]
    assert stored == 0


def test_the_owner_role_cannot_be_stripped_or_deleted(conn):
    with pytest.raises(roles.RoleError) as exc:
        roles.update_role(conn, owner(conn), 1, permissions=["register.read"])
    assert "always has every permission" in str(exc.value)
    with pytest.raises(roles.RoleError):
        roles.delete_role(conn, owner(conn), 1)
    # Renaming it is fine: it is the lecturer's word for their own job.
    roles.update_role(conn, owner(conn), 1, name="Course coordinator")
    assert roles.get_role(conn, owner(conn))["name"] == "Course coordinator"


def test_the_last_owner_cannot_be_demoted_or_disabled(conn):
    viewer = conn.execute("SELECT id FROM roles WHERE name = 'Viewer'").fetchone()["id"]
    with pytest.raises(roles.RoleError) as exc:
        roles.assign_role(conn, 1, viewer, 1)
    assert "last enabled" in str(exc.value)
    with pytest.raises(roles.RoleError):
        roles.assert_owner_survives(conn, losing_account_id=1)

    # With a second owner in place, both moves are allowed again.
    second = account(conn, "deputy", owner(conn))
    roles.assign_role(conn, 1, viewer, second)
    assert conn.execute("SELECT role_id FROM accounts WHERE id = 1").fetchone()["role_id"] == viewer


# -- nobody corrects their own attendance ----------------------------------------------------------

@pytest.fixture
def course(conn):
    """One course, one class, and a student who is also a course rep with an account."""
    from rollcall import courses
    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " source_name, device_name, active, created_at)"
                 " VALUES ('student', 2001, 1, 'PCT/001', 'ADE', 'Bola', 'ADE Bola', 'ADE Bola', 1, ?)",
                 (db.now(),))
    conn.execute("INSERT INTO people(role, device_user_id, device_id, matric_no, surname, other_names,"
                 " source_name, device_name, active, created_at)"
                 " VALUES ('student', 2002, 1, 'PCT/002', 'BALA', 'Sule', 'BALA Sule', 'BALA Sule', 1, ?)",
                 (db.now(),))
    level = conn.execute("SELECT id FROM levels WHERE level_number = 200").fetchone()["id"]
    conn.execute("INSERT INTO level_memberships SELECT p.id, 1, ? FROM people p WHERE p.role = 'student'",
                 (level,))
    course_id = courses.create_course(conn, 1, level, "PCT 201", "Pharmaceutics", 1)
    courses.enrol_level_members(conn, course_id, 1)
    conn.execute("INSERT INTO class_sessions(level_id, academic_session_id, course_id, date, start_time,"
                 " end_time, kind, created_by, created_at)"
                 " VALUES (?, 1, ?, '2026-10-05', '09:00', '11:00', 'manual', 1, ?)",
                 (level, course_id, db.now()))
    conn.commit()
    session_id = conn.execute("SELECT id FROM class_sessions ORDER BY id DESC LIMIT 1").fetchone()["id"]
    rep_person = conn.execute("SELECT id FROM people WHERE matric_no = 'PCT/001'").fetchone()["id"]
    other_person = conn.execute("SELECT id FROM people WHERE matric_no = 'PCT/002'").fetchone()["id"]
    return {"course_id": course_id, "session_id": session_id,
            "rep_person": rep_person, "other_person": other_person}


def test_an_account_cannot_correct_the_student_it_belongs_to(conn, course):
    rep_role = roles.create_role(conn, "Rep who can correct", "", ["register.correct"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    # The role carries register.correct. The refusal is not about permissions.
    assert roles.has(conn, rep, "register.correct")
    with pytest.raises(roles.RoleError) as exc:
        register.add_mark(conn, course["session_id"], course["rep_person"], "present", "I was there", rep)
    assert "for yourself" in str(exc.value)
    # The same account correcting somebody else is fine.
    register.add_mark(conn, course["session_id"], course["other_person"], "present", "Scanner failed", rep)


def test_an_account_cannot_excuse_itself(conn, course):
    rep_role = roles.create_role(conn, "Rep who can excuse", "", ["excusal.manage"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    with pytest.raises(roles.RoleError):
        register.add_excusal(conn, course["rep_person"], "2026-10-05", "2026-10-05", "medical",
                             "My own note", rep)


def test_one_account_per_person(conn, course):
    role_ = roles.create_role(conn, "Rep", "", [], 1)
    account(conn, "rep", role_, course["rep_person"])
    with pytest.raises(sqlite3.IntegrityError):
        account(conn, "rep2", role_, course["rep_person"])


# -- correction requests ---------------------------------------------------------------------------

def test_a_request_is_approved_by_someone_else_and_signed_by_them(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    request_id = register.request_correction(conn, course["session_id"], course["other_person"],
                                             "present", "Scanner would not read his thumb", rep)

    result = register.decide_request(conn, request_id, True, "Checked the queue video", 1)
    assert result["state"] == "approved"
    mark = conn.execute("SELECT * FROM attendance_marks WHERE id = ?", (result["mark_id"],)).fetchone()
    # The mark is signed by the lecturer who approved it, never by the rep who asked.
    assert mark["account_id"] == 1
    assert mark["person_id"] == course["other_person"]
    assert "requested, approved" in mark["note"]


def test_a_rejected_request_writes_no_mark_and_keeps_the_reason(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    request_id = register.request_correction(conn, course["session_id"], course["other_person"],
                                             "present", "He says he was there", rep)
    register.decide_request(conn, request_id, False, "He was not on the scan list or the queue video", 1)
    assert conn.execute("SELECT COUNT(*) FROM attendance_marks").fetchone()[0] == 0
    row = conn.execute("SELECT * FROM correction_requests WHERE id = ?", (request_id,)).fetchone()
    assert row["state"] == "rejected"
    assert "queue video" in row["decision_note"]


def test_a_rejection_must_say_why(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    request_id = register.request_correction(conn, course["session_id"], course["other_person"],
                                             "present", "He says he was there", rep)
    with pytest.raises(register.RegisterError):
        register.decide_request(conn, request_id, False, "", 1)


def test_nobody_decides_their_own_request(conn, course):
    both = roles.create_role(conn, "Rep who approves", "", ["register.request", "register.approve"], 1)
    rep = account(conn, "rep", both, course["rep_person"])
    request_id = register.request_correction(conn, course["session_id"], course["other_person"],
                                             "present", "He was there", rep)
    with pytest.raises(register.RegisterError) as exc:
        register.decide_request(conn, request_id, True, "", rep)
    assert "your own request" in str(exc.value)


def test_a_request_cannot_be_raised_for_yourself(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    with pytest.raises(roles.RoleError):
        register.request_correction(conn, course["session_id"], course["rep_person"], "present",
                                    "I was there", rep)


def test_one_open_request_per_student_per_class(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    register.request_correction(conn, course["session_id"], course["other_person"], "present", "First", rep)
    with pytest.raises(register.RegisterError) as exc:
        register.request_correction(conn, course["session_id"], course["other_person"], "present", "Again", rep)
    assert "already a request waiting" in str(exc.value)


def test_requests_are_append_only_and_decided_once(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    request_id = register.request_correction(conn, course["session_id"], course["other_person"],
                                             "present", "Scanner failed", rep)
    register.decide_request(conn, request_id, True, "Fine", 1)

    with pytest.raises(register.RegisterError):
        register.decide_request(conn, request_id, False, "Changed my mind", 1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM correction_requests WHERE id = ?", (request_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE correction_requests SET note = 'rewritten' WHERE id = ?", (request_id,))
    # The Python check above would catch a second decision through decide_request, so prove the
    # database refuses it too. Otherwise the trigger could be deleted and every test would still pass.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE correction_requests SET state = 'rejected' WHERE id = ?", (request_id,))


def test_a_rep_sees_only_their_own_requests(conn, course):
    rep_role = roles.create_role(conn, "Rep", "", ["register.request"], 1)
    rep = account(conn, "rep", rep_role, course["rep_person"])
    other = account(conn, "rep2", rep_role)
    register.request_correction(conn, course["session_id"], course["other_person"], "present", "Mine", rep)
    register.request_correction(conn, course["session_id"], course["rep_person"], "present", "Theirs", other)
    assert len(register.list_requests(conn)) == 2
    assert [r["note"] for r in register.list_requests(conn, requested_by=rep)] == ["Mine"]


# -- upgrading a database that already has accounts -------------------------------------------------

def test_version_4_admins_and_viewers_keep_working(tmp_path):
    conn = db.connect(tmp_path / "old.db")
    db.initialise(conn, target=4)
    conn.execute("INSERT INTO accounts(username, display_name, role, password_hash, created_at)"
                 " VALUES ('lecturer', 'Lecturer', 'admin', 'x', ?)", (db.now(),))
    conn.execute("INSERT INTO accounts(username, display_name, role, password_hash, created_at)"
                 " VALUES ('ta', 'TA', 'viewer', 'x', ?)", (db.now(),))
    conn.commit()

    db.initialise(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION

    lecturer = conn.execute("SELECT * FROM accounts WHERE username = 'lecturer'").fetchone()
    ta = conn.execute("SELECT * FROM accounts WHERE username = 'ta'").fetchone()
    assert roles.permissions_for(conn, lecturer) == roles.ALL_PERMISSIONS
    assert roles.get_role(conn, ta["role_id"])["name"] == "Viewer"
    assert not roles.has(conn, ta, "device.manage")
    assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.close()
