"""FastAPI application. Local only: binds to 127.0.0.1 and rejects any other Host header.

No `from __future__ import annotations` here: FastAPI must resolve the dependency aliases defined
inside create_app, and postponed annotations turn them into strings it cannot find.
"""

import os
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Iterator, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from . import (appearance, audit, auth, backups, courses, db, diagnostics, eligibility, enrollment, evidence,
               firstrun, groups, jobs,
               levels as levels_module, live, netsetup, pdf_fonts, progress, pulls, punches, register,
               reminders, restore, roles, roster, services, sheet_export, templates, today)
from . import NAME, VERSION
from .about import packages as about_packages, reset_password_command as about_reset_command
from .config import default_db_path
from .device import ADMIN, NORMAL, DeviceBusy, DeviceError, K40
from .names import device_name

COOKIE = "rollcall_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"


# -- request bodies --------------------------------------------------------------------------

class DeviceIn(BaseModel):
    name: str = "K40"
    ip: str = "192.168.1.201"
    port: int = 4370
    comm_key: int = 0


class SetupIn(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password: str
    academic_session: str = Field(min_length=4, examples=["2026/2027"])
    device: DeviceIn = DeviceIn()


class NetworkIn(BaseModel):
    """Which Ethernet adapter, by the index Windows gave it. Left out when there is only one."""
    adapter: int | None = None


class SetupNetworkIn(DeviceIn):
    """Setting up the Ethernet before any account exists: the terminal it is for, and the adapter."""
    adapter: int | None = None


class SetupDraftIn(BaseModel):
    """Whatever screen 1 has collected so far. Free-form because the steps own their own shape, and
    the password is dropped on the way in."""
    draft: dict


class CommitIn(BaseModel):
    confirm: list[str] = []


class LoginIn(BaseModel):
    username: str
    password: str


class AccountIn(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password: str
    role_id: int
    person_id: int | None = None


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = ""
    permissions: list[str] = []


class RolePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = None
    permissions: list[str] | None = None


class AssignRoleIn(BaseModel):
    role_id: int


class LinkPersonIn(BaseModel):
    person_id: int | None = None


class NewPasswordIn(BaseModel):
    password: str


class CorrectionRequestIn(BaseModel):
    person_id: int
    status: Literal["present", "absent"]
    note: str = Field(min_length=1)


class DecisionIn(BaseModel):
    approve: bool
    note: str = ""


class AcademicSessionIn(BaseModel):
    name: str = Field(min_length=4)
    make_current: bool = True


class LevelPatch(BaseModel):
    name: str | None = None
    code: str | None = None


class LevelIn(BaseModel):
    """A level to add. The number decides the block of device IDs, the name is the department's."""
    level_number: int
    name: str = ""


class DevicePatch(BaseModel):
    name: str | None = None
    ip: str | None = None
    port: int | None = None
    comm_key: int | None = None
    is_default: bool | None = None


class PushIn(BaseModel):
    level_id: int | None = None
    course_id: int | None = None
    person_ids: list[int] | None = None


class ClearLevelIn(BaseModel):
    """Deleting a level's roster is confirmed by typing the level's name."""
    confirm: str


class ConfirmSerialIn(BaseModel):
    """A destructive device action is confirmed by typing the terminal's serial."""
    confirm_serial: str


class StaffIn(BaseModel):
    surname: str = Field(min_length=1)
    other_names: str = ""
    device_user_id: int = Field(ge=1, le=999)
    super_admin: bool = True
    password: str | None = None
    device_id: int | None = None


class DeviceRoleIn(BaseModel):
    super_admin: bool
    password: str | None = None
    confirm_student: bool = False


class RemindLaterIn(BaseModel):
    days: int | None = None


class TemplatePatch(BaseModel):
    title: str | None = None
    course_code: str | None = None
    week1_start: str | None = None


class WeekIn(BaseModel):
    classes: int = Field(1, ge=0, le=7)
    starts_on: str | None = None
    label: str | None = None
    from_week: int | None = Field(default=None, ge=1, description="the number this week had before")


class WeeksIn(BaseModel):
    weeks: list[WeekIn]


class GenerateWeeksIn(BaseModel):
    weeks: int = Field(12, ge=1, le=52)
    classes_per_week: int = Field(1, ge=0, le=7)
    week1_start: str | None = None


class AttendancePlanIn(BaseModel):
    weeks: int | None = None
    classes_per_week: int | None = None
    total_classes: int | None = None
    threshold_percent: int | None = None


class FallbackPasswordIn(BaseModel):
    password: str
    reason: str


class DeactivateIn(BaseModel):
    note: str = Field(min_length=1)


class ForgetFingersIn(BaseModel):
    """Which fingerprint records to forget. No level means every level."""
    level_id: int | None = None


class EnrollIn(BaseModel):
    person_id: int
    finger_index: int = Field(ge=0, le=9)
    consent_confirmed: bool = False


class SessionIn(BaseModel):
    course_id: int
    date: str
    start_time: str
    end_time: str
    kind: Literal["device", "manual"] = "device"
    title: str | None = None
    group_id: int | None = None


class SplitIn(BaseModel):
    count: int = Field(ge=2, le=groups.MAX_GROUPS)
    order: Literal["matric", "surname"] = "matric"


class GroupIn(BaseModel):
    name: str | None = None


class GroupRenameIn(BaseModel):
    name: str = Field(min_length=1)


class GroupMoveIn(BaseModel):
    person_id: int
    group_id: int | None = Field(default=None, description="null takes them out of every group")
    how: Literal["from_today", "wrong_group"] = "from_today"


class GroupListIn(BaseModel):
    lines: list[str] = Field(max_length=2000)


class ClassGroupIn(BaseModel):
    group_id: int | None = Field(default=None, description="null is everybody on the course")


class CourseIn(BaseModel):
    level_id: int
    code: str = Field(min_length=1)
    title: str | None = None


class CoursePatch(BaseModel):
    code: str | None = None
    title: str | None = None


class StudentEntryIn(BaseModel):
    matric_no: str
    name: str | None = None
    level: str | int | None = None


class StudentEntriesIn(BaseModel):
    entries: list[StudentEntryIn]


class AssignCourseIn(BaseModel):
    course_id: int


class ExcusalIn(BaseModel):
    person_id: int
    date_from: str
    date_to: str
    category: Literal["medical", "official", "bereavement", "other"]
    note: str
    course_id: int | None = None


class CancelIn(BaseModel):
    note: str


class RestoreIn(BaseModel):
    """A restore may say why, but does not have to: the cancellation's own note is kept in the log."""
    note: str = ""


class SetupImportIn(BaseModel):
    """Importing another computer's data at first run: which staged file, and the new owner account.
    The file's own accounts never sign in here (restore.import_data)."""
    token: str
    username: str
    display_name: str
    password: str


class BackupRestoreIn(BaseModel):
    """Replacing the register with a backup: which staged file, and the password again."""
    token: str
    password: str


class MarkIn(BaseModel):
    person_id: int
    status: Literal["present", "absent"]
    note: str


SETTING_RULES = {
    "attendance_threshold_percent": (0, 100),
    "clock_drift_warn_seconds": (10, 3600),
    "auto_backup_after_pull": (0, 1),
    "backup_keep": (1, 100),
}


# Scripts, fonts and data only from the app itself: nothing is ever fetched from outside (PRD).
# Inline styles are allowed because components set per-element custom properties in style="".
CONTENT_SECURITY_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                           "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
                           "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
# FastAPI's generated API pages load Swagger UI from a CDN, so they are left without the policy.
DOCS_PATHS = {"/docs", "/redoc", "/docs/oauth2-redirect"}


def create_app(db_path: Path | None = None, k40_factory=K40) -> FastAPI:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    boot = db.connect(path)
    db.initialise(boot)
    boot.close()

    app = FastAPI(title=NAME, version=VERSION)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # OWASP HTTP Headers Cheat Sheet. The app is only reachable from this machine, but a page open
        # in the same browser can still frame it, sniff types or read a cached register.
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        path = request.url.path
        if path.startswith("/api/"):
            headers.setdefault("Cache-Control", "no-store")   # registers and names never sit in a cache
        else:
            # Revalidate every asset. The server is on loopback, so an ETag check costs nothing, and
            # the alternative is an upgraded Herewise still running last version's JavaScript out of
            # the browser cache with no way for anyone to tell.
            headers.setdefault("Cache-Control", "no-cache")
        if path not in DOCS_PATHS:
            headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response
    app.state.db_path = path
    app.state.login_throttle = auth.LoginThrottle()
    app.state.enrollment = enrollment.EnrollmentManager(path, factory=k40_factory)
    factory = k40_factory

    # -- dependencies --------------------------------------------------------------------

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(path)
        try:
            yield conn
        finally:
            conn.close()

    Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

    def current_account(request: Request, conn: Conn) -> sqlite3.Row:
        account = auth.account_for_token(conn, request.cookies.get(COOKIE))
        if account is None:
            raise HTTPException(401, "Please log in.")
        return account

    def requires(permission: str):
        """Gate a route on one permission. What holds it is whatever role someone gave the account."""
        def dependency(account: Annotated[sqlite3.Row, Depends(current_account)], conn: Conn) -> sqlite3.Row:
            if not roles.has(conn, account, permission):
                raise HTTPException(403, roles.denial(permission))
            return account
        return dependency

    Account = Annotated[sqlite3.Row, Depends(current_account)]
    Reader = Annotated[sqlite3.Row, Depends(requires("register.read"))]
    Puller = Annotated[sqlite3.Row, Depends(requires("register.pull"))]
    Corrector = Annotated[sqlite3.Row, Depends(requires("register.correct"))]
    Requester = Annotated[sqlite3.Row, Depends(requires("register.request"))]
    Approver = Annotated[sqlite3.Row, Depends(requires("register.approve"))]
    ClassManager = Annotated[sqlite3.Row, Depends(requires("class.manage"))]
    ExcusalManager = Annotated[sqlite3.Row, Depends(requires("excusal.manage"))]
    PlanManager = Annotated[sqlite3.Row, Depends(requires("plan.manage"))]
    EligibilityReader = Annotated[sqlite3.Row, Depends(requires("eligibility.view"))]
    EligibilityExporter = Annotated[sqlite3.Row, Depends(requires("eligibility.export"))]
    StudentReader = Annotated[sqlite3.Row, Depends(requires("students.read"))]
    RosterManager = Annotated[sqlite3.Row, Depends(requires("roster.manage"))]
    CourseManager = Annotated[sqlite3.Row, Depends(requires("courses.manage"))]
    Enroller = Annotated[sqlite3.Row, Depends(requires("enrollment.run"))]
    DeviceReader = Annotated[sqlite3.Row, Depends(requires("device.read"))]
    DeviceManager = Annotated[sqlite3.Row, Depends(requires("device.manage"))]
    AccountManager = Annotated[sqlite3.Row, Depends(requires("accounts.manage"))]
    RoleManager = Annotated[sqlite3.Row, Depends(requires("roles.manage"))]
    SettingsManager = Annotated[sqlite3.Row, Depends(requires("settings.manage"))]
    AuditReader = Annotated[sqlite3.Row, Depends(requires("audit.read"))]
    BackupTaker = Annotated[sqlite3.Row, Depends(requires("backup.run"))]
    Restorer = Annotated[sqlite3.Row, Depends(requires("backup.restore"))]

    def default_device_id(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT id FROM devices ORDER BY is_default DESC, id LIMIT 1").fetchone()
        if row is None:
            raise HTTPException(400, "No device is set up.")
        return row["id"]

    def ensure_device_free() -> None:
        if app.state.enrollment.busy():
            raise HTTPException(409, "An enrolment is in progress. Wait for it to finish.")

    def refuse_other_origin(request: Request) -> None:
        """For the routes that make Windows ask for administrator rights. The session cookie is
        SameSite=Strict and a JSON body needs a preflight no other origin can pass, so this is the
        third lock, not the only one: a page from anywhere else never gets as far as the prompt."""
        origin = request.headers.get("origin")
        if origin and origin != "null":
            host = origin.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
            if host not in ("127.0.0.1", "localhost", "testserver"):
                raise HTTPException(403, "Only Herewise's own window can change this computer's network.")

    # -- errors --------------------------------------------------------------------------

    @app.exception_handler(DeviceBusy)
    async def _busy(_: Request, exc: DeviceBusy):
        return JSONResponse({"error": exc.message, "hint": exc.hint, "code": exc.code}, status_code=409)

    @app.exception_handler(DeviceError)
    async def _device(_: Request, exc: DeviceError):
        return JSONResponse({"error": exc.message, "hint": exc.hint, "code": exc.code}, status_code=502)

    for kind in (services.ServiceError, roster.RosterError, register.RegisterError, enrollment.EnrollmentError,
                 reminders.ReminderError, templates.TemplateError, courses.CourseError,
                 evidence.EvidenceError, roles.RoleError, firstrun.SetupError, restore.RestoreError,
                 levels_module.LevelError, live.LiveError, netsetup.NetworkError, groups.GroupError):
        @app.exception_handler(kind)
        async def _bad_request(_: Request, exc: Exception):
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        # Headers kept: Retry-After on a slowed login would otherwise never reach the screen.
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    # -- setup and auth ------------------------------------------------------------------

    @app.get("/api/setup/status")
    def setup_status(conn: Conn):
        accounts = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        saved = firstrun.read_draft(conn) if accounts == 0 else None
        return {"needs_setup": accounts == 0, "resume": saved,
                "this_computer": diagnostics.local_ipv4_addresses()}

    @app.put("/api/setup/draft")
    def save_setup_draft(body: SetupDraftIn, conn: Conn):
        """Keep the answers so far, so someone can close the app and carry on later (known gap 2)."""
        firstrun.refuse_if_done(conn)
        return firstrun.save_draft(conn, body.draft)

    @app.delete("/api/setup/draft")
    def discard_setup_draft(conn: Conn):
        firstrun.refuse_if_done(conn)
        firstrun.clear_draft(conn)
        return {"ok": True}

    @app.post("/api/setup/test-device")
    def test_setup_device(body: DeviceIn, conn: Conn):
        """Test the cable before an account exists. The ordinary diagnose route needs a saved device."""
        return firstrun.test_connection(conn, body.ip, body.port, body.comm_key, factory=factory)

    @app.post("/api/setup/network")
    def setup_network(body: SetupNetworkIn, request: Request, conn: Conn):
        """Setup's own way to the same Ethernet change, because a new computer meets the problem here
        first. Refused once an account exists, like the rest of setup; after that it is Device's."""
        firstrun.refuse_if_done(conn)
        refuse_other_origin(request)
        result = netsetup.apply(body.ip, body.adapter)
        return {"setup": result,
                "tested": firstrun.test_connection(conn, body.ip, body.port, body.comm_key, factory=factory)}

    @app.post("/api/setup")
    def setup(body: SetupIn, response: Response, conn: Conn):
        if conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
            raise HTTPException(409, "Setup has already been done.")
        try:
            auth.validate_new_password(body.password)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        with db.transaction(conn):
            account_id = auth.create_account(conn, body.username, body.display_name, body.password,
                                             roles.owner_role_id(conn))
            conn.execute("INSERT INTO academic_sessions(name, is_current, created_at) VALUES (?, 1, ?)",
                         (body.academic_session.strip(), db.now()))
            conn.execute("INSERT INTO devices(name, ip, port, comm_key, is_default, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                         (body.device.name, body.device.ip, body.device.port, body.device.comm_key, db.now()))
            db.audit(conn, account_id, "setup", "accounts", account_id, "first owner account created")
            # The draft has become the database, so it stops existing. Nothing else reads it again.
            conn.execute("DELETE FROM setup_drafts WHERE id = 1")
        token, _ = auth.login(conn, body.username, body.password)
        _set_cookie(response, token)
        return {"account_id": account_id}

    # -- importing another computer's data, at first run ------------------------------------------
    #
    # Asked for on 2026-09-23: set up the real register on one laptop, then move "all the data" to the
    # lecturer's, "only the data, not the account name and password". The file is the one Settings,
    # Backup downloads. These run before an account exists, and only then: once anybody has one they
    # refuse, and replacing that register needs the signed-in restore with a password.

    @app.post("/api/setup/import/inspect")
    def setup_import_inspect(conn: Conn, file: UploadFile = File(...)):
        firstrun.refuse_if_done(conn)
        data_folder = app.state.db_path.parent
        token = restore.stage_upload(data_folder, file.file, file.filename)
        try:
            held = restore.inspect(restore.staged(data_folder, token), need_owner=False)
        except restore.RestoreError:
            restore.discard(data_folder, token)
            raise
        return {"token": token, "label": restore.label_of(data_folder, token), "backup": held,
                "terminal": restore.terminal_of(restore.staged(data_folder, token))}

    @app.post("/api/setup/import")
    def setup_import(body: SetupImportIn, response: Response, conn: Conn):
        firstrun.refuse_if_done(conn)
        data_folder = app.state.db_path.parent
        source = restore.staged(data_folder, body.token)
        done = restore.import_data(conn, source, backups.folder(conn), body.username, body.display_name,
                                   body.password, restore.label_of(data_folder, body.token))
        restore.discard(data_folder, body.token)
        token, _ = auth.login(conn, body.username.strip(), body.password)
        _set_cookie(response, token)
        return done

    @app.delete("/api/setup/import/{token}")
    def setup_import_cancel(token: str, conn: Conn):
        firstrun.refuse_if_done(conn)
        restore.discard(app.state.db_path.parent, token)
        return {"ok": True}

    @app.post("/api/login")
    def login(body: LoginIn, response: Response, conn: Conn):
        throttle = app.state.login_throttle
        wait = throttle.wait_seconds(body.username)
        if wait:
            raise HTTPException(429, f"Too many wrong attempts. Wait {wait} seconds, then try again.",
                                headers={"Retry-After": str(wait)})
        result = auth.login(conn, body.username, body.password)
        if result is None:
            throttle.failed(body.username)
            raise HTTPException(401, "Wrong username or password.")
        throttle.succeeded(body.username)
        token, account = result
        _set_cookie(response, token)
        # The screen shows these straight after login: this is where the Super Admin question is asked.
        pending = reminders.pending(conn) if roles.has(conn, account, "device.manage") else []
        return {**_account_dict(conn, account), "reminders": pending}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, conn: Conn):
        auth.logout(conn, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(account: Account, conn: Conn):
        pending = reminders.pending(conn) if roles.has(conn, account, "device.manage") else []
        return {**_account_dict(conn, account), "reminders": pending}

    @app.get("/api/accounts")
    def list_accounts(_: AccountManager, conn: Conn):
        return [_account_dict(conn, r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")]

    @app.post("/api/accounts")
    def add_account(body: AccountIn, admin: AccountManager, conn: Conn):
        role = roles.get_role(conn, body.role_id)
        try:
            with db.transaction(conn):
                account_id = auth.create_account(conn, body.username, body.display_name, body.password,
                                                 body.role_id, body.person_id)
                db.audit(conn, admin["id"], "account.create", "accounts", account_id,
                         f"{body.username} as {role['name']}")
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise HTTPException(400, "That username is taken." if isinstance(exc, sqlite3.IntegrityError) else str(exc))
        return {"account_id": account_id}

    @app.post("/api/accounts/{account_id}/role")
    def set_account_role(account_id: int, body: AssignRoleIn, admin: AccountManager, conn: Conn):
        roles.assign_role(conn, account_id, body.role_id, admin["id"])
        return _account_dict(conn, conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    @app.post("/api/accounts/{account_id}/person")
    def set_account_person(account_id: int, body: LinkPersonIn, admin: AccountManager, conn: Conn):
        """Tie an account to the student it belongs to, so the app can refuse self-corrections."""
        roles.link_person(conn, account_id, body.person_id, admin["id"])
        return _account_dict(conn, conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())

    @app.post("/api/accounts/{account_id}/password")
    def set_account_password(account_id: int, body: NewPasswordIn, admin: AccountManager, conn: Conn):
        """Give someone a new password after they have forgotten theirs (known gap 3)."""
        target = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "Unknown account.")
        try:
            with db.transaction(conn):
                auth.set_password(conn, account_id, body.password)
                db.audit(conn, admin["id"], "account.password", "accounts", account_id,
                         target["username"])
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "signed_out": True}

    @app.post("/api/accounts/{account_id}/enable")
    def enable_account(account_id: int, admin: AccountManager, conn: Conn):
        """Turn a disabled account back on (known gap 3). There was no way back before this."""
        target = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "Unknown account.")
        if not target["disabled"]:
            raise HTTPException(400, "That account is already on.")
        with db.transaction(conn):
            conn.execute("UPDATE accounts SET disabled = 0 WHERE id = ?", (account_id,))
            db.audit(conn, admin["id"], "account.enable", "accounts", account_id, target["username"])
        return _account_dict(conn, conn.execute("SELECT * FROM accounts WHERE id = ?",
                                                (account_id,)).fetchone())

    @app.post("/api/accounts/{account_id}/disable")
    def disable_account(account_id: int, admin: AccountManager, conn: Conn):
        if account_id == admin["id"]:
            raise HTTPException(400, "You cannot disable your own account.")
        target = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if target is None:
            raise HTTPException(404, "Unknown account.")
        roles.assert_owner_survives(conn, losing_account_id=account_id)
        with db.transaction(conn):
            conn.execute("UPDATE accounts SET disabled = 1 WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM auth_sessions WHERE account_id = ?", (account_id,))
            db.audit(conn, admin["id"], "account.disable", "accounts", account_id, target["username"])
        return {"ok": True}

    # -- roles ---------------------------------------------------------------------------

    @app.get("/api/permissions")
    def list_permissions(_: Account):
        """The fixed vocabulary a role is built from. Fixed because code enforces each one."""
        return roles.describe()

    @app.get("/api/roles")
    def list_roles(_: Account, conn: Conn):
        return roles.list_roles(conn)

    @app.post("/api/roles")
    def add_role(body: RoleIn, admin: RoleManager, conn: Conn):
        role_id = roles.create_role(conn, body.name, body.description, body.permissions, admin["id"])
        return {"role_id": role_id}

    @app.patch("/api/roles/{role_id}")
    def patch_role(role_id: int, body: RolePatch, admin: RoleManager, conn: Conn):
        roles.update_role(conn, role_id, admin["id"], name=body.name, description=body.description,
                          permissions=body.permissions)
        return dict(roles.get_role(conn, role_id))

    @app.delete("/api/roles/{role_id}")
    def remove_role(role_id: int, admin: RoleManager, conn: Conn):
        roles.delete_role(conn, role_id, admin["id"])
        return {"ok": True}

    # -- academic sessions and levels ----------------------------------------------------

    @app.get("/api/academic-sessions")
    def list_academic_sessions(_: Account, conn: Conn):
        return [dict(r) for r in conn.execute("SELECT * FROM academic_sessions ORDER BY name")]

    @app.post("/api/academic-sessions")
    def add_academic_session(body: AcademicSessionIn, admin: SettingsManager, conn: Conn):
        with db.transaction(conn):
            if body.make_current:
                conn.execute("UPDATE academic_sessions SET is_current = 0")
            try:
                cur = conn.execute("INSERT INTO academic_sessions(name, is_current, created_at) VALUES (?, ?, ?)",
                                   (body.name.strip(), 1 if body.make_current else 0, db.now()))
            except sqlite3.IntegrityError:
                raise HTTPException(400, "That academic session already exists.")
            db.audit(conn, admin["id"], "academic_session.create", "academic_sessions", cur.lastrowid, body.name)
        return {"id": cur.lastrowid}

    @app.post("/api/academic-sessions/{session_id}/make-current")
    def make_current(session_id: int, admin: SettingsManager, conn: Conn):
        with db.transaction(conn):
            if not conn.execute("SELECT 1 FROM academic_sessions WHERE id = ?", (session_id,)).fetchone():
                raise HTTPException(404, "Unknown academic session.")
            conn.execute("UPDATE academic_sessions SET is_current = (id = ?)", (session_id,))
            db.audit(conn, admin["id"], "academic_session.make_current", "academic_sessions", session_id)
        return {"ok": True}

    @app.get("/api/levels")
    def list_levels(_: Account, conn: Conn):
        rows = conn.execute(
            "SELECT l.*, (SELECT COUNT(*) FROM level_memberships m JOIN academic_sessions a"
            " ON a.id = m.academic_session_id AND a.is_current = 1 JOIN people p ON p.id = m.person_id"
            " WHERE m.level_id = l.id AND p.active = 1) AS students FROM levels l ORDER BY l.level_number"
        )
        # Each row carries why it cannot be removed, so the screen can show the control disabled
        # with the reason written on it rather than leaving it out.
        out = []
        for row in rows:
            held = levels_module.references(conn, row["id"])
            out.append({**dict(row), "can_remove": not held,
                        "holds": {levels_module.plain_name(table, count): count
                                  for table, count in sorted(held.items())},
                        "why_not_removable": levels_module.why_not_removable(conn, row["id"])})
        return out

    @app.post("/api/levels")
    def add_level(body: LevelIn, admin: RosterManager, conn: Conn):
        """Add a year the department runs. Some stop at 400, some go to 700."""
        return levels_module.add(conn, body.level_number, admin["id"], body.name)

    @app.delete("/api/levels/{level_id}")
    def remove_level(level_id: int, admin: RosterManager, conn: Conn):
        """Remove a year the department does not run. Only while nothing points at it, and only
        with the terminal answering, because anybody in its block of IDs comes off the terminal."""
        ensure_device_free()
        return services.remove_level(conn, level_id, admin["id"], factory)

    @app.get("/api/levels/{level_id}/clear")
    def clear_level_preview(level_id: int, _: RosterManager, conn: Conn):
        """What deleting a level's roster would delete, counted, for the dialog that asks first."""
        return levels_module.clear_preview(conn, level_id)

    @app.post("/api/levels/{level_id}/clear")
    def clear_level(level_id: int, body: ClearLevelIn, admin: RosterManager, conn: Conn):
        """Delete a level's students, courses, classes and attendance, and take the students and their
        fingerprints off the terminal first. Refused while the terminal does not answer."""
        ensure_device_free()
        return services.clear_level(conn, level_id, body.confirm, admin["id"], factory)

    @app.patch("/api/levels/{level_id}")
    def patch_level(level_id: int, body: LevelPatch, admin: RosterManager, conn: Conn):
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if fields:
            with db.transaction(conn):
                conn.execute(f"UPDATE levels SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             [*fields.values(), level_id])
                db.audit(conn, admin["id"], "level.update", "levels", level_id, str(fields))
        return dict(conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone())

    # -- devices -------------------------------------------------------------------------

    @app.get("/api/devices")
    def list_devices(_: DeviceReader, conn: Conn):
        return [dict(r) for r in conn.execute("SELECT * FROM devices ORDER BY id")]

    @app.post("/api/devices")
    def add_device(body: DeviceIn, admin: DeviceManager, conn: Conn):
        with db.transaction(conn):
            cur = conn.execute("INSERT INTO devices(name, ip, port, comm_key, created_at) VALUES (?, ?, ?, ?, ?)",
                               (body.name, body.ip, body.port, body.comm_key, db.now()))
            db.audit(conn, admin["id"], "device.create", "devices", cur.lastrowid, f"{body.name} {body.ip}")
        return {"id": cur.lastrowid}

    @app.patch("/api/devices/{device_id}")
    def patch_device(device_id: int, body: DevicePatch, admin: DeviceManager, conn: Conn):
        services.device_row(conn, device_id)
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        with db.transaction(conn):
            if fields.pop("is_default", None):
                conn.execute("UPDATE devices SET is_default = (id = ?)", (device_id,))
            if fields:
                conn.execute(f"UPDATE devices SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                             [*fields.values(), device_id])
            db.audit(conn, admin["id"], "device.update", "devices", device_id, str(body.model_dump()))
        return dict(services.device_row(conn, device_id))

    @app.get("/api/devices/{device_id}/diagnose")
    def diagnose_device(device_id: int, _: DeviceReader, conn: Conn):
        row = services.device_row(conn, device_id)
        return netsetup.diagnosis(row["ip"], row["port"])

    @app.post("/api/devices/{device_id}/network/setup")
    def network_setup(device_id: int, body: NetworkIn, request: Request, admin: DeviceManager, conn: Conn):
        """Put this computer's Ethernet on the terminal's network: one prompt from Windows, then the
        adapter is read again and the chain walked again, so the screen shows what Windows did."""
        refuse_other_origin(request)
        row = services.device_row(conn, device_id)
        result = netsetup.apply(row["ip"], body.adapter)
        if result["result"] == "done":
            db.audit(conn, admin["id"], "device.network_setup", "devices", device_id,
                     f"{result['adapter']}, {result['address']}")
        return {"setup": result, "diagnosis": netsetup.diagnosis(row["ip"], row["port"])}

    @app.post("/api/devices/{device_id}/network/undo")
    def network_undo(device_id: int, body: NetworkIn, request: Request, admin: DeviceManager, conn: Conn):
        """Take the terminal's address and route back off this computer's Ethernet."""
        refuse_other_origin(request)
        row = services.device_row(conn, device_id)
        result = netsetup.undo(row["ip"], body.adapter)
        if result["result"] == "done":
            db.audit(conn, admin["id"], "device.network_undo", "devices", device_id,
                     f"{result['adapter']}, {result['address'] or 'the route only'}")
        return {"setup": result, "diagnosis": netsetup.diagnosis(row["ip"], row["port"])}

    @app.get("/api/jobs/current")
    def current_job(_: Account):
        """What the long operation running right now is doing, for the bar on the screen that
        started it. There is only ever one, because every device route goes through
        ensure_device_free()."""
        return jobs.current() or {"state": "idle"}

    @app.get("/api/devices/{device_id}/ping")
    def device_ping(device_id: int, _: DeviceReader, conn: Conn):
        """The heartbeat behind the chip in the top bar. Never disables the terminal, and answers
        "busy" rather than queueing behind a pull, so it cannot delay one."""
        return services.ping(conn, device_id, factory)

    @app.get("/api/devices/{device_id}/status")
    def device_status(device_id: int, _: DeviceReader, conn: Conn):
        ensure_device_free()
        return services.status(conn, device_id, factory)

    @app.post("/api/devices/{device_id}/sync-time")
    def device_sync_time(device_id: int, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.sync_time(conn, device_id, admin["id"], factory)

    @app.post("/api/devices/{device_id}/restart")
    def device_restart(device_id: int, admin: DeviceManager, conn: Conn):
        """Restart the terminal and wait for it: the cure for one that has stopped taking captures."""
        ensure_device_free()
        return services.restart_device(conn, device_id, admin["id"], factory)

    @app.post("/api/devices/{device_id}/pull")
    def device_pull(device_id: int, account: Puller, conn: Conn):
        ensure_device_free()
        result = services.pull_attendance(conn, device_id, account["id"], factory)
        # New scans become classes on the attendance sheet without the lecturer creating each one.
        result["detected_sessions"] = register.detect_sessions(conn, account["id"])
        # A copy of the register at the moment it changed, so nobody has to remember to take one.
        result["backup"] = backups.after_pull(conn, result, account["id"])
        return result

    @app.post("/api/devices/{device_id}/push")
    def device_push(device_id: int, body: PushIn, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.push_people(conn, device_id, admin["id"], person_ids=body.person_ids,
                                    level_id=body.level_id, factory=factory, course_id=body.course_id)

    @app.post("/api/devices/{device_id}/sync-fingers")
    def device_sync_fingers(device_id: int, _: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.sync_fingers(conn, device_id, factory)

    @app.post("/api/devices/{device_id}/people/{person_id}/remove")
    def remove_person_from_device(device_id: int, person_id: int, admin: DeviceManager, conn: Conn):
        """Take one person off the terminal. Their record and their scans stay here."""
        ensure_device_free()
        return services.remove_from_device(conn, device_id, person_id, admin["id"], factory)

    @app.post("/api/fingers/forget")
    def forget_fingers(body: ForgetFingersIn, admin: DeviceManager, conn: Conn):
        """Forget the fingerprint records this register holds. The terminal is not touched."""
        return services.forget_fingers(conn, admin["id"], body.level_id)

    @app.post("/api/devices/{device_id}/empty")
    def empty_device(device_id: int, body: ConfirmSerialIn, admin: DeviceManager, conn: Conn):
        """Take everybody and every fingerprint off the terminal, leaving its scans alone."""
        ensure_device_free()
        return services.empty_device_people(conn, device_id, admin["id"], body.confirm_serial, factory)

    @app.post("/api/devices/{device_id}/clear-attendance")
    def device_clear(device_id: int, body: ConfirmSerialIn, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.clear_device_attendance(conn, device_id, admin["id"], body.confirm_serial, factory)

    @app.post("/api/devices/{device_id}/unlock-menu")
    def device_unlock(device_id: int, body: ConfirmSerialIn, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.unlock_menu(conn, device_id, admin["id"], body.confirm_serial, factory)

    @app.get("/api/devices/{device_id}/roles")
    def device_roles(device_id: int, _: DeviceReader, conn: Conn):
        services.device_row(conn, device_id)
        return services.roles_summary(conn, device_id)

    # -- roster --------------------------------------------------------------------------

    @app.post("/api/levels/{level_id}/roster/preview")
    async def roster_preview(level_id: int, admin: RosterManager, conn: Conn, file: UploadFile = File(...),
                             device_id: int | None = Form(None), sheet: str | None = Form(None),
                             matric_col: int | None = Form(None), name_col: int | None = Form(None),
                             other_col: int | None = Form(None), level_col: int | None = Form(None),
                             first_row: int | None = Form(None)):
        # A CSV, or the .xls or .xlsx the portal hands out, or a department's own workbook with a
        # sheet per year. What is stored with the import is the rows as read, so the commit cannot
        # read the file differently from the preview.
        #
        # When the file cannot say which column is which, the answer is the question rather than a
        # refusal: {"needs_columns": true, ...} with the first rows and a guess. The screen sends the
        # same file back with sheet, matric_col, name_col (columns from 0) and first_row (from 1).
        level = conn.execute("SELECT level_number FROM levels WHERE id = ?", (level_id,)).fetchone()
        if level is None:
            raise HTTPException(400, "Unknown level.")
        choice = None
        if matric_col is not None and name_col is not None:
            choice = roster.Choice(matric_col, name_col, first_row or 1, other_col, level_col)
        try:
            rows = roster.parse_upload(await file.read(roster.MAX_UPLOAD_BYTES + 1), file.filename or "",
                                       level["level_number"], sheet, choice)
        except roster.NeedsColumns as asking:
            return asking.payload()
        text = roster.as_csv(rows)
        academic = register.current_academic_session(conn)
        device = device_id or default_device_id(conn)
        plan = roster.build_plan(conn, level_id, academic["id"], device, rows)
        cur = conn.execute(
            "INSERT INTO roster_imports(level_id, academic_session_id, device_id, file_name, csv_text, status,"
            " created_at, account_id) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (level_id, academic["id"], device, file.filename, text, db.now(), admin["id"]),
        )
        return {"import_id": cur.lastrowid, **plan}

    @app.get("/api/levels/{level_id}/imports")
    def level_imports(level_id: int, _: RosterManager, conn: Conn):
        """Every committed import for a level, and whether it can still be taken back."""
        return {"imports": roster.imports_for(conn, level_id)}

    @app.post("/api/roster-imports/{import_id}/undo")
    def undo_import(import_id: int, admin: RosterManager, conn: Conn):
        """Take back an import that went into the wrong level, while its students are untouched."""
        return roster.undo(conn, import_id, admin["id"])

    @app.post("/api/roster-imports/{import_id}/commit")
    def roster_commit(import_id: int, admin: RosterManager, conn: Conn, body: CommitIn | None = None):
        # `confirm` names the warnings the preview gave that the person ticked (roster._warnings).
        return roster.commit(conn, import_id, admin["id"], body.confirm if body else ())

    @app.get("/api/levels/{level_id}/roster/template")
    def roster_template(level_id: int, _: RosterManager, conn: Conn):
        """A blank roster with the headings Herewise reads, for a list typed in by hand."""
        level = conn.execute("SELECT * FROM levels WHERE id = ?", (level_id,)).fetchone()
        if level is None:
            raise HTTPException(400, "Unknown level.")
        return Response(roster.template(level["name"]),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{level["name"]} roster template.xlsx"'})

    @app.post("/api/roster-imports/{import_id}/discard")
    def roster_discard(import_id: int, _: RosterManager, conn: Conn):
        updated = conn.execute("UPDATE roster_imports SET status = 'discarded' WHERE id = ? AND status = 'pending'",
                               (import_id,)).rowcount
        if not updated:
            raise HTTPException(400, "Nothing pending to discard.")
        return {"ok": True}

    # -- people and enrollment -----------------------------------------------------------

    @app.get("/api/levels/{level_id}/students")
    def level_students(level_id: int, _: StudentReader, conn: Conn):
        return enrollment.level_progress(conn, level_id)

    @app.get("/api/staff")
    def list_staff(_: RosterManager, conn: Conn):
        rows = conn.execute(
            "SELECT id, device_user_id, device_id, surname, other_names, device_name, device_privilege,"
            " device_password IS NOT NULL AS has_password, on_device, active,"
            " (SELECT COUNT(*) FROM fingers f WHERE f.person_id = people.id) AS fingers"
            " FROM people WHERE role = 'staff' ORDER BY device_user_id")
        return [dict(r) for r in rows]

    @app.post("/api/staff")
    def add_staff(body: StaffIn, admin: RosterManager, conn: Conn):
        password = _device_password(body.password, required=body.super_admin)
        device = body.device_id or default_device_id(conn)
        try:
            with db.transaction(conn):
                cur = conn.execute(
                    "INSERT INTO people(role, device_user_id, device_id, surname, other_names, source_name, device_name,"
                    " device_privilege, device_password, created_at) VALUES ('staff', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (body.device_user_id, device, body.surname.strip(), body.other_names.strip(),
                     f"{body.surname} {body.other_names}".strip(), device_name(body.surname, body.other_names),
                     ADMIN if body.super_admin else NORMAL, password, db.now()),
                )
                db.audit(conn, admin["id"], "staff.create", "people", cur.lastrowid,
                         f"ID {body.device_user_id}, super_admin={body.super_admin}")
        except sqlite3.IntegrityError:
            raise HTTPException(400, f"Device ID {body.device_user_id} is already used.")
        return {"person_id": cur.lastrowid}

    @app.post("/api/people/{person_id}/device-role")
    def set_device_role(person_id: int, body: DeviceRoleIn, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        person = conn.execute("SELECT * FROM people WHERE id = ? AND active = 1", (person_id,)).fetchone()
        if person is None:
            raise HTTPException(404, "Unknown person.")
        if body.super_admin and person["role"] == "student" and not body.confirm_student:
            raise HTTPException(400, "This person is a student. A student Super Admin can open the device menu, "
                                     "delete scans on the device and enrol fingers for others. Confirm to continue.")
        password = _device_password(body.password, required=False) or person["device_password"]
        if body.super_admin and not password:
            raise HTTPException(400, "A Super Admin needs a 1 to 8 digit keypad password.")
        privilege = ADMIN if body.super_admin else NORMAL

        # Saved only once the device has the new role. Saving first let a failed push turn the reminder
        # that cannot be cancelled into one that can, while the terminal stayed unprotected.
        def save(c: sqlite3.Connection) -> None:
            c.execute("UPDATE people SET device_privilege = ?, device_password = ? WHERE id = ?",
                      (privilege, password, person_id))
            db.audit(c, admin["id"], "person.device_role", "people", person_id, f"super_admin={body.super_admin}")

        push = services.push_people(conn, person["device_id"], admin["id"], person_ids=[person_id], factory=factory,
                                    changes={person_id: {"device_privilege": privilege, "device_password": password}},
                                    then=save)
        left = reminders.count_admins(conn, person["device_id"])
        warning = None
        if left == 0:
            warning = "The device now has no Super Admin. Anyone at the keypad can open the menu."
        elif left == 1:
            warning = "The device has one Super Admin. You will be reminded to choose a second."
        return {"person_id": person_id, "super_admin": body.super_admin, "pushed": push["pushed"],
                "super_admins_on_device": left, "warning": warning}

    @app.get("/api/devices/{device_id}/admin-candidates")
    def admin_candidates(device_id: int, _: DeviceManager, conn: Conn):
        services.device_row(conn, device_id)
        return reminders.admin_candidates(conn, device_id)

    @app.get("/api/reminders")
    def list_reminders(_: DeviceManager, conn: Conn):
        return reminders.pending(conn)

    @app.post("/api/reminders/{key}/remind-later")
    def reminder_later(key: str, body: RemindLaterIn, admin: DeviceManager, conn: Conn):
        return reminders.remind_later(conn, key, body.days, admin["id"])

    @app.post("/api/reminders/{key}/cancel")
    def reminder_cancel(key: str, admin: DeviceManager, conn: Conn):
        return reminders.cancel(conn, key, admin["id"])

    @app.post("/api/reminders/{key}/restore")
    def reminder_restore(key: str, admin: DeviceManager, conn: Conn):
        return reminders.restore(conn, key, admin["id"])

    @app.post("/api/people/{person_id}/fallback-password")
    def fallback_password(person_id: int, body: FallbackPasswordIn, admin: DeviceManager, conn: Conn):
        ensure_device_free()
        return services.set_fallback_password(conn, person_id, body.password, body.reason, admin["id"], factory)

    class StudentEditIn(BaseModel):
        surname: str = Field(min_length=1, max_length=120)
        other_names: str = Field("", max_length=160)
        matric_no: str | None = Field(default=None, max_length=40)

    @app.put("/api/people/{person_id}")
    def edit_person(person_id: int, body: StudentEditIn, admin: RosterManager, conn: Conn):
        """Correct a student's name or matric number, or add the number a direct-entry student lacked.

        A changed name is sent to the terminal straight away when the student is on it, because the
        terminal shows it at every scan. If the terminal cannot take it now, the edit still stands
        and the student is sent with the next push.
        """
        done = roster.edit_student(conn, person_id, body.surname, body.other_names, body.matric_no, admin["id"])
        done["terminal"] = None
        if done.get("device_name_changed") and done.get("was_on_device") and not app.state.enrollment.busy():
            try:
                services.push_people(conn, done["device_id"], admin["id"], person_ids=[person_id], factory=factory)
                done["terminal"] = "sent"
            except (DeviceError, services.ServiceError) as exc:
                done["terminal"] = f"not sent: {getattr(exc, 'message', exc)}"
        return done

    @app.post("/api/people/{person_id}/deactivate")
    def deactivate(person_id: int, body: DeactivateIn, admin: RosterManager, conn: Conn):
        with db.transaction(conn):
            if not conn.execute("UPDATE people SET active = 0 WHERE id = ?", (person_id,)).rowcount:
                raise HTTPException(404, "Unknown person.")
            db.audit(conn, admin["id"], "person.deactivate", "people", person_id, body.note)
        return {"ok": True, "note": "Their scans are kept. Remove them from the device separately if needed."}

    @app.post("/api/enrollment/start")
    def enrollment_start(body: EnrollIn, admin: Enroller, conn: Conn):
        # A capture holds the terminal for up to a minute, and a queue at it is scanning for a class.
        taking = live.open_class(conn)
        if taking is not None:
            raise HTTPException(409, f"{taking['code']} is taking attendance on the terminal. End it "
                                     "before enrolling anyone.")
        return app.state.enrollment.start(conn, body.person_id, body.finger_index, admin["id"], body.consent_confirmed)

    @app.delete("/api/people/{person_id}/fingers/{finger_index}")
    def remove_finger(person_id: int, finger_index: int, admin: Enroller, conn: Conn):
        """Take one enrolled finger off the terminal and out of the register, for one captured by
        mistake. The terminal changes first; the register follows what it reports back."""
        ensure_device_free()
        return enrollment.remove_finger(conn, person_id, finger_index, admin["id"], factory)

    @app.post("/api/enrollment/cancel")
    def cancel_enrollment(admin: Enroller, conn: Conn):
        """Stop a capture that is waiting for a finger, for one started by mistake."""
        done = app.state.enrollment.cancel()
        db.audit(conn, admin["id"], "enrollment.cancel", "people", done.get("person_id"),
                 f"stopped the capture for {done.get('name') or 'a student'}")
        return done

    @app.get("/api/enrollment/status")
    def enrollment_status(_: Enroller):
        return app.state.enrollment.status()

    # -- a class taken live -----------------------------------------------------------------
    # Start in the room, the queue scans, End when it is done (asked for on 2026-09-22).

    class LiveStartIn(BaseModel):
        week_number: int | None = Field(default=None, ge=1, description="the week of the sheet")
        # A course with groups must be told: a group's id, or "everybody" for the whole course.
        group_id: int | Literal["everybody"] | None = None

    class LiveEndIn(BaseModel):
        ended_at: str | None = Field(default=None, description="HH:MM on the class's own day")

    def live_view(conn: sqlite3.Connection, class_id: int, terminal: dict) -> dict:
        return {"register": register.session_register(conn, class_id), "terminal": terminal}

    @app.get("/api/live")
    def live_status(_: Reader, conn: Conn):
        """Whether a class is taking attendance, for any screen. Never touches the terminal."""
        return live.status(conn)

    @app.get("/api/courses/{course_id}/live/weeks")
    def live_weeks(course_id: int, _: Puller, conn: Conn, group_id: int | None = None):
        """Which week of the sheet a class about to start could go in, and the one to suggest. For a
        group's class, counted on that group's sheet."""
        if group_id is not None:
            groups._of_course(conn, course_id, group_id)
        return live.week_choices(conn, course_id, group_id=group_id)

    @app.post("/api/courses/{course_id}/live")
    def live_start(course_id: int, account: Puller, conn: Conn, body: LiveStartIn | None = None):
        ensure_device_free()
        class_id = live.start(conn, course_id, account["id"], factory,
                              week_number=body.week_number if body else None,
                              group_id=body.group_id if body else None)
        return live_view(conn, class_id, live.refresh(conn, class_id, factory, force=True))

    @app.post("/api/live/{class_id}/refresh")
    def live_refresh(class_id: int, _: Puller, conn: Conn):
        """Take in whatever has been scanned since the last look. Cheap when nobody has."""
        if app.state.enrollment.busy():
            terminal = {"state": "busy", "detail": "An enrolment is holding the terminal."}
        else:
            terminal = live.refresh(conn, class_id, factory)
        return live_view(conn, class_id, terminal)

    @app.post("/api/live/{class_id}/end")
    def live_end(class_id: int, body: LiveEndIn, account: Puller, conn: Conn):
        ensure_device_free()
        return live.end(conn, class_id, account["id"], factory, body.ended_at)

    @app.post("/api/live/{class_id}/reopen")
    def live_reopen(class_id: int, account: Corrector, conn: Conn):
        """Open an ended class again for whoever had not scanned (asked for on 2026-10-22).

        Gated on correcting attendance, because its effect is a correction: absent becomes present
        on a class already counted. Someone who may only ask for corrections asks for those instead.
        It also reads the terminal, so it needs that permission too.
        """
        if not roles.has(conn, account, "register.pull"):
            raise HTTPException(403, roles.denial("register.pull"))
        ensure_device_free()
        live.reopen(conn, class_id, account["id"], factory)
        return live_view(conn, class_id, live.refresh(conn, class_id, factory, force=True))

    # -- today ---------------------------------------------------------------------------

    @app.get("/api/today")
    def today_summary(_: Reader, conn: Conn, date: str | None = None):
        """Screen 4 in one shape: the last pull, today's classes with their counts, what is waiting."""
        _check_dates(date)
        return today.today(conn, date)

    @app.get("/api/rail")
    def rail(_: Reader, conn: Conn):
        """The rail footer: the biggest level this session and how many students it holds."""
        return today.rail_footer(conn)

    # -- punches -------------------------------------------------------------------------

    @app.get("/api/imports/{batch_id}")
    def import_batch(batch_id: int, _: Reader, conn: Conn):
        """Screen 5: what one pull brought in, and the reasoning behind every class it inferred."""
        try:
            return pulls.batch(conn, batch_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/imports")
    def latest_import(_: Reader, conn: Conn):
        return pulls.latest(conn)

    @app.get("/api/punches/unmatched")
    def unmatched(_: Reader, conn: Conn):
        return punches.unmatched(conn)

    @app.post("/api/imports/usb")
    def usb_import(_: Puller):
        # PRD 8.4: the parser is written against a real export from this device, not documentation.
        raise HTTPException(501, "USB import is waiting on a real attendance file exported from this K40.")

    # -- courses and carry-over students ------------------------------------------------

    @app.get("/api/courses")
    def list_courses(_: Reader, conn: Conn, academic_session_id: int | None = None,
                     with_figures: bool = False):
        """Every course this session. `with_figures` adds the four numbers a course card shows.

        It is opt-in because each course's figures are a full pass over its register, which is
        nothing for the four to ten courses one lecturer keeps and would not be for forty.
        """
        academic = academic_session_id or register.current_academic_session(conn)["id"]
        rows = courses.list_courses(conn, academic)
        if with_figures:
            for row in rows:
                row["figures"] = register.course_figures(conn, row["id"])
        # What each course has recorded against it, so the list can offer Delete on the row it
        # belongs to, disabled with the reason when it cannot go.
        for row in rows:
            held = courses.holds(conn, row["id"])
            row["holds"] = register.name_holds(held)
            row["blocking"] = register.name_holds(register.blocking(held))
            row["can_delete"] = not row["blocking"]
        return rows

    @app.post("/api/courses")
    def add_course(body: CourseIn, admin: CourseManager, conn: Conn):
        academic = register.current_academic_session(conn)["id"]
        course_id = courses.create_course(conn, academic, body.level_id, body.code, body.title, admin["id"])
        return {**dict(courses.get_course(conn, course_id)),
                "template_id": templates.ensure_template(conn, course_id)}

    @app.get("/api/courses/{course_id}")
    def get_course(course_id: int, _: Reader, conn: Conn, with_figures: bool = False):
        row = {**dict(courses.get_course(conn, course_id)),
               "template_id": templates.ensure_template(conn, course_id)}
        members = courses.members(conn, course_id)
        row["level_students"] = sum(1 for m in members if m["kind"] == "level")
        row["carry_over_students"] = sum(1 for m in members if m["kind"] == "carry_over")
        # Empty for a course taken with its whole roster, which is every course until it is split.
        row["groups"] = groups.list_groups(conn, course_id)
        row["ungrouped"] = len(groups.ungrouped(conn, course_id))
        if with_figures:
            row["figures"] = register.course_figures(conn, course_id)
        return row

    @app.patch("/api/courses/{course_id}")
    def patch_course(course_id: int, body: CoursePatch, admin: CourseManager, conn: Conn):
        return courses.update_course(conn, course_id, admin["id"], body.code, body.title)

    @app.get("/api/courses/{course_id}/holds")
    def course_holds(course_id: int, _: Reader, conn: Conn):
        """What has been recorded against this course, so a screen can say why it cannot go."""
        courses.get_course(conn, course_id)
        held = courses.holds(conn, course_id)
        stops = register.blocking(held)
        return {"holds": register.name_holds(held), "blocking": register.name_holds(stops),
                "can_delete": not stops}

    @app.delete("/api/courses/{course_id}")
    def delete_course(course_id: int, admin: CourseManager, conn: Conn):
        """A course nothing was ever recorded against. CourseError becomes a 400 with the sentence,
        the same as every other refusal here."""
        return courses.delete_course(conn, course_id, admin["id"])

    @app.get("/api/courses/{course_id}/students")
    def course_students(course_id: int, _: Reader, conn: Conn, include_removed: bool = False):
        courses.get_course(conn, course_id)
        return [{"person_id": r["id"], "device_user_id": r["device_user_id"], "matric_no": r["matric_no"],
                 "surname": r["surname"], "other_names": r["other_names"], "kind": r["kind"],
                 "level": r["level_number"], "added_at": r["added_at"], "removed_at": r["removed_at"],
                 "removed_note": r["removed_note"], "on_device": bool(r["on_device"])}
                for r in courses.members(conn, course_id, include_removed)]

    @app.post("/api/courses/{course_id}/students/preview")
    async def carry_over_preview(course_id: int, _: CourseManager, conn: Conn, request: Request,
                                 file: UploadFile | None = File(None)):
        """Preview adding students. Send a CSV or Excel file (matric_no, name, level), or JSON
        {"entries": [...]}."""
        if file is not None:
            entries = roster.parse_upload(await file.read(roster.MAX_UPLOAD_BYTES + 1), file.filename or "")
        else:
            try:
                entries = (await request.json()).get("entries") or []
            except ValueError:
                raise HTTPException(400, "Send a CSV file or a JSON body with entries.")
        return courses.carry_over_plan(conn, course_id, entries)

    @app.post("/api/courses/{course_id}/students")
    def carry_over_commit(course_id: int, body: StudentEntriesIn, admin: CourseManager, conn: Conn):
        return courses.carry_over_commit(conn, course_id, [e.model_dump() for e in body.entries], admin["id"])

    # -- a course's groups ---------------------------------------------------------------
    # Asked for on 2026-09-29: split a course into groups A to D and take a class for one of them,
    # while other courses keep their whole roster. The rules are in groups.py.

    @app.get("/api/courses/{course_id}/groups")
    def course_groups(course_id: int, _: Reader, conn: Conn):
        """The groups, and every student on the course with the group they are in today."""
        courses.get_course(conn, course_id)
        current = groups.groups_on(conn, course_id)
        listed = groups.list_groups(conn, course_id)
        students = []
        for p in courses.members(conn, course_id):
            g = current.get(p["id"])
            students.append({"person_id": p["id"], "device_user_id": p["device_user_id"],
                             "matric_no": p["matric_no"], "surname": p["surname"],
                             "other_names": p["other_names"], "kind": p["kind"], "level": p["level_number"],
                             "group_id": g["id"] if g else None, "group": g["name"] if g else None,
                             # What moving them would keep with their present group, so the screen
                             # asks the from-today question only when there is something to keep.
                             "classes_with_group": groups.classes_with_group(conn, course_id, p["id"]) if g else 0})
        return {"groups": listed, "students": students,
                "ungrouped": sum(1 for s in students if s["group_id"] is None) if listed else 0,
                "group_classes": sum(g["classes"] for g in listed)}

    @app.post("/api/courses/{course_id}/groups/split")
    def split_course(course_id: int, body: SplitIn, admin: CourseManager, conn: Conn):
        return {"groups": groups.split(conn, course_id, body.count, body.order, admin["id"])}

    @app.post("/api/courses/{course_id}/groups")
    def add_group(course_id: int, body: GroupIn, admin: CourseManager, conn: Conn):
        return groups.add_group(conn, course_id, body.name, admin["id"])

    @app.delete("/api/courses/{course_id}/groups")
    def clear_groups(course_id: int, admin: CourseManager, conn: Conn):
        """Every group away, to split again. Refused once a class has been taken for one."""
        return groups.clear_groups(conn, course_id, admin["id"])

    @app.patch("/api/groups/{group_id}")
    def rename_group(group_id: int, body: GroupRenameIn, admin: CourseManager, conn: Conn):
        return groups.rename_group(conn, group_id, body.name, admin["id"])

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: int, admin: CourseManager, conn: Conn):
        return groups.delete_group(conn, group_id, admin["id"])

    @app.post("/api/courses/{course_id}/groups/move")
    def move_to_group(course_id: int, body: GroupMoveIn, admin: CourseManager, conn: Conn):
        return groups.move(conn, course_id, body.person_id, body.group_id, body.how, admin["id"])

    @app.post("/api/courses/{course_id}/groups/share-out")
    def share_out(course_id: int, admin: CourseManager, conn: Conn):
        """Everybody in no group into the smallest groups: students who joined after the split."""
        return groups.share_out(conn, course_id, admin["id"])

    @app.post("/api/groups/{group_id}/list/preview")
    def group_list_preview(group_id: int, body: GroupListIn, _: CourseManager, conn: Conn):
        """What pasting a department's list into this group would do. Changes nothing."""
        group = groups.get_group(conn, group_id)
        return groups.list_plan(conn, group["course_id"], group_id, body.lines)

    @app.post("/api/groups/{group_id}/list")
    def group_list_commit(group_id: int, body: GroupListIn, admin: CourseManager, conn: Conn):
        group = groups.get_group(conn, group_id)
        return groups.list_commit(conn, group["course_id"], group_id, body.lines, admin["id"])

    @app.post("/api/courses/{course_id}/students/{person_id}/remove")
    def remove_course_student(course_id: int, person_id: int, body: DeactivateIn, admin: CourseManager, conn: Conn):
        courses.remove_student(conn, course_id, person_id, body.note, admin["id"])
        return {"ok": True}

    # -- classes and registers ----------------------------------------------------------

    @app.get("/api/sessions")
    def list_sessions(_: Reader, conn: Conn, course_id: int | None = None, date_from: str | None = None,
                      date_to: str | None = None):
        query, params = "SELECT * FROM class_sessions WHERE 1 = 1", []
        for clause, value in (("course_id = ?", course_id), ("date >= ?", date_from), ("date <= ?", date_to)):
            if value is not None:
                query += f" AND {clause}"
                params.append(value)
        rows = conn.execute(query + " ORDER BY date DESC, start_time DESC", params).fetchall()
        # What each class has recorded against it, so its row can offer Delete disabled with the
        # reason rather than offering nothing at all.
        out = []
        for row in rows:
            held = register.holds(conn, row["id"])
            stops = register.blocking(held)
            # The week of the sheet it sits in, by the sheet's own rule, so the Classes tab groups a
            # class where the sheet shows it rather than by the calendar week of its date.
            out.append({**dict(row), "holds": register.name_holds(held),
                        "blocking": register.name_holds(stops), "can_delete": not stops,
                        "sheet_week": live.sheet_week(conn, row), "open": register.is_open(row),
                        "reopened": len(register.reopenings(conn, row["id"])) if row["opened_at"] else 0})
        return out

    class MoveWeekIn(BaseModel):
        week_number: int = Field(ge=1)

    @app.put("/api/sessions/{session_id}/group")
    def set_session_group(session_id: int, body: ClassGroupIn, admin: ClassManager, conn: Conn):
        """Say which group a class was for, or that it was for everybody on the course."""
        return groups.set_class_group(conn, session_id, body.group_id, admin["id"])

    @app.put("/api/sessions/{session_id}/week")
    def move_session_week(session_id: int, body: MoveWeekIn, admin: ClassManager, conn: Conn):
        """Put a class in another week of its course's sheet."""
        return live.move_to_week(conn, session_id, body.week_number, admin["id"])

    @app.get("/api/sessions/unassigned")
    def list_unassigned(_: Reader, conn: Conn):
        return register.unassigned_sessions(conn)

    @app.get("/api/sessions/suggest")
    def suggest_session(course_id: int, day: str, _: Reader, conn: Conn):
        return register.suggest_window(conn, course_id, day)

    @app.post("/api/sessions")
    def add_session(body: SessionIn, admin: ClassManager, conn: Conn):
        session_id = register.create_session(conn, body.course_id, body.date, body.start_time, body.end_time,
                                             body.kind, admin["id"], body.title, body.group_id)
        return {"id": session_id}

    @app.post("/api/sessions/detect")
    def detect_sessions(admin: ClassManager, conn: Conn):
        return {"created": register.detect_sessions(conn, admin["id"])}

    @app.post("/api/sessions/{session_id}/course")
    def assign_session_course(session_id: int, body: AssignCourseIn, admin: ClassManager, conn: Conn):
        register.assign_course(conn, session_id, body.course_id, admin["id"])
        return {"ok": True}

    @app.post("/api/sessions/{session_id}/cancel")
    def cancel_session(session_id: int, body: CancelIn, admin: ClassManager, conn: Conn):
        register.cancel_session(conn, session_id, body.note, admin["id"])
        return {"ok": True}

    @app.delete("/api/sessions/{session_id}")
    def delete_session(session_id: int, admin: ClassManager, conn: Conn):
        """A class that recorded nothing. One that did is cancelled, never deleted."""
        return register.delete_session(conn, session_id, admin["id"])

    @app.post("/api/sessions/{session_id}/restore")
    def restore_session(session_id: int, body: RestoreIn, admin: ClassManager, conn: Conn):
        """Undo a cancellation. Known gap 15: a class cancelled by mistake had no way back."""
        register.restore_session(conn, session_id, body.note, admin["id"])
        return {"ok": True}

    @app.get("/api/sessions/{session_id}/register")
    def session_register(session_id: int, _: Reader, conn: Conn):
        # Whether the class can be opened again for whoever had not scanned, and why not if not.
        return {**register.session_register(conn, session_id), "reopen": live.reopen_offer(conn, session_id)}

    @app.get("/api/sessions/{session_id}/students/{person_id}")
    def session_cell(session_id: int, person_id: int, _: Reader, conn: Conn):
        """One box on the sheet, with every mark ever written for it: the correction drawer's contract."""
        return register.cell(conn, session_id, person_id)

    @app.post("/api/sessions/{session_id}/marks")
    def add_mark(session_id: int, body: MarkIn, admin: Corrector, conn: Conn):
        mark_id = register.add_mark(conn, session_id, body.person_id, body.status, body.note, admin["id"])
        return {"id": mark_id}

    # -- excused absences ---------------------------------------------------------------

    @app.get("/api/correction-requests")
    def list_correction_requests(account: Account, conn: Conn, state: str | None = None,
                                 course_id: int | None = None):
        """Everyone with `register.approve` sees every request. Everyone else sees only their own."""
        if roles.has(conn, account, "register.approve"):
            return register.list_requests(conn, state=state, course_id=course_id)
        return register.list_requests(conn, state=state, course_id=course_id, requested_by=account["id"])

    @app.post("/api/sessions/{session_id}/correction-requests")
    def add_correction_request(session_id: int, body: CorrectionRequestIn, account: Requester, conn: Conn):
        request_id = register.request_correction(conn, session_id, body.person_id, body.status, body.note,
                                                 account["id"])
        return {"request_id": request_id}

    @app.post("/api/correction-requests/{request_id}/decide")
    def decide_correction_request(request_id: int, body: DecisionIn, account: Approver, conn: Conn):
        return register.decide_request(conn, request_id, body.approve, body.note, account["id"])

    @app.post("/api/excusals")
    def add_excusal(body: ExcusalIn, admin: ExcusalManager, conn: Conn):
        excusal_id = register.add_excusal(conn, body.person_id, body.date_from, body.date_to, body.category,
                                          body.note, admin["id"], body.course_id)
        return {"id": excusal_id}

    @app.get("/api/excusals")
    def list_excusals(_: Reader, conn: Conn, person_id: int | None = None, course_id: int | None = None):
        return register.list_excusals(conn, person_id, course_id)

    @app.post("/api/excusals/{excusal_id}/revoke")
    def revoke_excusal(excusal_id: int, body: DeactivateIn, admin: ExcusalManager, conn: Conn):
        register.revoke_excusal(conn, excusal_id, body.note, admin["id"])
        return {"ok": True}

    # -- percentages, plan, eligibility ---------------------------------------------------

    def _check_dates(*values: str | None) -> None:
        for value in values:
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise HTTPException(400, "Dates must be YYYY-MM-DD.")

    @app.get("/api/courses/{course_id}/summary")
    def course_summary(course_id: int, _: Reader, conn: Conn, date_from: str | None = None,
                       date_to: str | None = None, threshold_percent: int | None = None, weeks: int | None = None,
                       classes_per_week: int | None = None, total_classes: int | None = None):
        """Attendance percentages for the course. The optional numbers are a what-if that is not saved."""
        _check_dates(date_from, date_to)
        return register.course_summary(conn, course_id, date_from, date_to, threshold_percent, weeks,
                                       classes_per_week, total_classes)

    @app.get("/api/courses/{course_id}/progress")
    def course_progress(course_id: int, _: EligibilityReader, conn: Conn, date_from: str | None = None,
                        date_to: str | None = None):
        """Where every student stands today: percentage so far, what they still need, and who cannot
        reach the pass mark any more."""
        _check_dates(date_from, date_to)
        return progress.progress(conn, course_id, date_from, date_to)

    @app.get("/api/courses/{course_id}/progress/export")
    def export_progress(course_id: int, account: EligibilityExporter, conn: Conn,
                        format: Literal["xlsx", "pdf"] = "pdf",
                        variant: Literal["notice", "at_risk"] = "notice",
                        date_from: str | None = None, date_to: str | None = None):
        """The notice to post (matric numbers and percentages) or the lecturer's at-risk list."""
        _check_dates(date_from, date_to)
        data = progress.progress(conn, course_id, date_from, date_to)
        if format == "xlsx":
            content = progress.to_xlsx(data, variant)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            content = progress.to_pdf(data, variant, db.get_setting(conn, "paper_size"))
            media = "application/pdf"
        db.audit(conn, account["id"], f"progress.export.{format}.{variant}", "courses", course_id)
        name = progress.filename(data, format, variant)
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/courses/{course_id}/attendance-plan")
    def get_attendance_plan(course_id: int, _: Reader, conn: Conn):
        courses.get_course(conn, course_id)
        return register.get_plan(conn, course_id)

    @app.put("/api/courses/{course_id}/attendance-plan")
    def put_attendance_plan(course_id: int, body: AttendancePlanIn, admin: PlanManager, conn: Conn):
        return register.save_plan(conn, course_id, admin["id"], body.weeks, body.classes_per_week,
                                  body.total_classes, body.threshold_percent)

    @app.get("/api/courses/{course_id}/eligibility")
    def course_eligibility(course_id: int, _: EligibilityReader, conn: Conn, date_from: str | None = None,
                           date_to: str | None = None):
        _check_dates(date_from, date_to)
        return eligibility.eligibility(conn, course_id, date_from, date_to)

    @app.get("/api/courses/{course_id}/eligibility/export")
    def export_eligibility(course_id: int, account: EligibilityExporter, conn: Conn, format: Literal["xlsx", "pdf"] = "pdf",
                           variant: Literal["full", "notice"] = "full", date_from: str | None = None,
                           date_to: str | None = None):
        _check_dates(date_from, date_to)
        data = eligibility.eligibility(conn, course_id, date_from, date_to)
        if format == "xlsx":
            content = eligibility.to_xlsx(data, variant)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            content = eligibility.to_pdf(data, variant, db.get_setting(conn, "paper_size"))
            media = "application/pdf"
        db.audit(conn, account["id"], f"eligibility.export.{format}.{variant}", "courses", course_id)
        name = eligibility.filename(data, format, variant)
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # -- attendance sheet template ------------------------------------------------------

    @app.get("/api/courses/{course_id}/template")
    def course_template(course_id: int, _: Reader, conn: Conn):
        courses.get_course(conn, course_id)
        t = templates.get_template(conn, templates.ensure_template(conn, course_id))
        # How many classes each week holds, so Sheet setup can say why a week cannot be removed.
        for w in t["weeks"]:
            w["held"] = len(templates.week_classes(conn, course_id, w))
        return t

    @app.patch("/api/templates/{template_id}")
    def patch_template(template_id: int, body: TemplatePatch, admin: PlanManager, conn: Conn):
        return templates.update_template(conn, template_id, admin["id"], body.title, body.course_code,
                                         body.week1_start)

    @app.put("/api/templates/{template_id}/weeks")
    def put_template_weeks(template_id: int, body: WeeksIn, admin: PlanManager, conn: Conn):
        return templates.set_weeks(conn, template_id, admin["id"], [w.model_dump() for w in body.weeks])

    @app.post("/api/templates/{template_id}/weeks/generate")
    def generate_template_weeks(template_id: int, body: GenerateWeeksIn, admin: PlanManager, conn: Conn):
        return templates.generate_weeks(conn, template_id, admin["id"], body.weeks, body.classes_per_week,
                                        body.week1_start)

    @app.get("/api/templates/{template_id}/sheet")
    def template_sheet(template_id: int, _: Reader, conn: Conn, group: str | None = None):
        """The sheet. For a course with groups, one group's (``group`` is its id, or "none" for the
        students in no group); the first group's when none is named."""
        return templates.grid(conn, template_id, group=group)

    @app.get("/api/templates/{template_id}/export")
    def export_template(template_id: int, account: Reader, conn: Conn, format: Literal["xlsx", "pdf"] = "xlsx",
                        group: str | None = None):
        """One sheet, or with ``group=all`` every group's sheet in one file, each on its own pages
        (the PDF) or its own worksheet (the spreadsheet)."""
        if group == "all":
            t = templates.get_template(conn, template_id)
            views = [g["id"] for g in groups.list_groups(conn, t["course_id"])]
            if groups.ungrouped(conn, t["course_id"]):
                views.append(templates.NO_GROUP)
            sheets = [templates.grid(conn, template_id, group=v) for v in views] or [templates.grid(conn, template_id)]
        else:
            sheets = [templates.grid(conn, template_id, group=group)]
        paper = db.get_setting(conn, "paper_size")
        if format == "xlsx":
            content = sheet_export.to_xlsx_many(sheets, paper)
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            content = sheet_export.to_pdf_many(sheets, paper)
            media = "application/pdf"
        db.audit(conn, account["id"], f"template.export.{format}", "register_templates", template_id,
                 "every group" if group == "all" else (sheets[0].get("group") or {}).get("name"))
        name = sheet_export.filename(sheets[0], format, every_group=group == "all")
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # -- student evidence ---------------------------------------------------------------

    @app.get("/api/students/search")
    def search_students(q: str, _: StudentReader, conn: Conn):
        return evidence.search(conn, q)

    @app.get("/api/students/{person_id}/evidence")
    def student_evidence(person_id: int, _: StudentReader, conn: Conn, course_id: int | None = None):
        return evidence.student_evidence(conn, person_id, course_id)

    # -- settings, audit, backup ---------------------------------------------------------

    @app.get("/api/settings")
    def get_settings(_: Account, conn: Conn):
        # Defaults first: a setting added in a later version has no row until someone saves it.
        return {**db.DEFAULT_SETTINGS, **{r["key"]: r["value"] for r in conn.execute("SELECT * FROM settings")}}

    @app.put("/api/settings")
    def put_settings(body: dict[str, str], admin: SettingsManager, conn: Conn):
        with db.transaction(conn):
            for key, value in body.items():
                if key == "excused_rule":
                    if value not in ("excluded", "present"):
                        raise HTTPException(400, "excused_rule must be excluded or present.")
                elif key == "paper_size":
                    if value not in pdf_fonts.PAPER_SIZES:
                        raise HTTPException(400, "paper_size must be a4 or letter.")
                elif key in SETTING_RULES:
                    low, high = SETTING_RULES[key]
                    if not (str(value).isdigit() and low <= int(value) <= high):
                        raise HTTPException(400, f"{key} must be a whole number from {low} to {high}.")
                else:
                    raise HTTPException(400, f"Unknown setting {key}.")
                # Upsert: a plain UPDATE silently saved nothing for a key added after the database was made.
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)"
                             " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
            db.audit(conn, admin["id"], "settings.update", detail=str(body))
        return get_settings(admin, conn)

    @app.get("/api/audit")
    def audit_log(_: AuditReader, conn: Conn, limit: int = 200, date_from: str | None = None,
                  date_to: str | None = None, account_id: int | None = None,
                  group: str | None = None):
        """Who did what, narrowed and written as sentences (known gap 17)."""
        _check_dates(date_from, date_to)
        return {"entries": audit.query(conn, date_from=date_from, date_to=date_to,
                                       account_id=account_id, group=group, limit=limit),
                "actors": audit.actors(conn),
                "groups": list(audit.GROUPS)}

    @app.get("/api/audit/export")
    def audit_export(account: AuditReader, conn: Conn, date_from: str | None = None,
                     date_to: str | None = None, account_id: int | None = None,
                     group: str | None = None):
        _check_dates(date_from, date_to)
        rows = audit.query(conn, date_from=date_from, date_to=date_to, account_id=account_id,
                           group=group, limit=5000)
        content = audit.to_csv(rows)
        span = f"{date_from or 'start'}-to-{date_to or 'today'}"
        db.audit(conn, account["id"], "audit.export", detail=f"{len(rows)} entries, {span}")
        return Response(content, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="herewise-activity-{span}.csv"'})

    @app.get("/api/about")
    def about(_: Account, conn: Conn):
        """Screen 40. Licences are read from the installed packages (rollcall/about.py).

        pyzk is GPL-2.0, which decides this app's own licence the day a copy is handed over. It is
        stated here rather than in a document nobody opens (docs/RELEASE-READINESS.md).
        """
        fonts = [{"name": "Inter", "licence": "SIL Open Font License 1.1",
                  "file": "/fonts/Inter-OFL.txt"},
                 {"name": "Instrument Serif", "licence": "SIL Open Font License 1.1",
                  "file": "/fonts/InstrumentSerif-OFL.txt"}]
        device = conn.execute("SELECT name, ip, port, serial, firmware, platform FROM devices"
                              " ORDER BY is_default DESC, id LIMIT 1").fetchone()
        return {
            "name": NAME,
            "version": VERSION,
            "studio": "Emberfig",
            "data_folder": str(app.state.db_path.parent),
            "packages": about_packages(),
            "reset_password_command": about_reset_command(),
            "fonts": fonts,
            "device": dict(device) if device else None,
            "licence_note": "Herewise is free software under the GNU General Public License version 2 "
                            "or any later version, and its source is published beside every "
                            "installer. pyzk, which speaks the terminal's protocol, is under the "
                            "GNU GPL as well.",
        }

    @app.get("/api/backups")
    def list_backups(_: BackupTaker, conn: Conn):
        """Every copy in the data folder, newest first, so a screen can show the last one."""
        return {"backups": backups.listing(conn), "folder": str(backups.folder(conn) or "")}

    @app.get("/api/backup")
    def backup(admin: BackupTaker, conn: Conn):
        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        tmp = Path(name)
        target = sqlite3.connect(tmp)
        try:
            conn.backup(target)
        finally:
            target.close()
        db.audit(conn, admin["id"], "backup.download")
        # Named for the button that fetches it, Download your data, and readable at a glance on a USB
        # stick: herewise-data-2026-09-23-2152.db.
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        return FileResponse(tmp, filename=f"herewise-data-{stamp}.db",
                            background=BackgroundTask(tmp.unlink, missing_ok=True))

    # -- restore (known gap 14): look first, replace second, rollcall/restore.py -------------

    @app.post("/api/restore/inspect")
    def restore_inspect(account: Restorer, conn: Conn, file: UploadFile | None = File(None),
                        name: str | None = Form(None)):
        """Stage a backup, from an uploaded file or one of the copies on this computer, and say what
        it holds beside what the register holds now. Nothing in the register changes."""
        data_folder = app.state.db_path.parent
        if file is not None:
            token = restore.stage_upload(data_folder, file.file, file.filename)
        elif name:
            token = restore.stage_copy(data_folder, backups.folder(conn), name)
        else:
            raise HTTPException(400, "Choose a backup file, or one of the copies on this computer.")
        try:
            held = restore.inspect(restore.staged(data_folder, token))
        except restore.RestoreError:
            restore.discard(data_folder, token)
            raise
        return {"token": token, "label": restore.label_of(data_folder, token), "backup": held,
                "current": restore.summary(conn),
                "your_account_in_backup": account["username"] in held["accounts"]}

    @app.post("/api/restore")
    def restore_now(body: BackupRestoreIn, account: Restorer, conn: Conn, response: Response):
        """Replace the register with a staged backup. Asks for the password again, because this
        replaces everything and the person at the keyboard should be the person signed in."""
        ensure_device_free()
        if not auth.verify_password(body.password, account["password_hash"]):
            raise HTTPException(403, "That password is not right. Nothing has been changed.")
        data_folder = app.state.db_path.parent
        source = restore.staged(data_folder, body.token)
        done = restore.restore(conn, source, backups.folder(conn), account,
                               restore.label_of(data_folder, body.token))
        restore.discard(data_folder, body.token)
        response.delete_cookie(COOKIE, path="/")
        return done

    @app.delete("/api/restore/{token}")
    def restore_cancel(token: str, _: Restorer):
        restore.discard(app.state.db_path.parent, token)
        return {"ok": True}

    # -- how it looks on this computer ------------------------------------------------------
    # System, Light or Dark (asked for on 2026-10-22). Kept beside the register, not in it, and
    # read by the page's head before it paints (rollcall/appearance.py).

    class AppearanceIn(BaseModel):
        theme: Literal["system", "light", "dark"]

    @app.get("/api/appearance.js")
    def appearance_script():
        """Before anything else, on every screen including sign in and setup, so nothing flashes."""
        return Response(appearance.script(appearance.read(app.state.db_path.parent)),
                        media_type="text/javascript")

    @app.get("/api/appearance")
    def appearance_read():
        return {"theme": appearance.read(app.state.db_path.parent), "choices": list(appearance.CHOICES)}

    @app.put("/api/appearance")
    def appearance_write(body: AppearanceIn, request: Request, conn: Conn):
        """Anyone signed in on this computer, or anybody during first-run setup, which offers it once.
        It changes nothing in the register, so it needs no permission and writes no activity row."""
        if firstrun.done(conn) and auth.account_for_token(conn, request.cookies.get(COOKIE)) is None:
            raise HTTPException(401, "Please log in.")
        return {"theme": appearance.write(app.state.db_path.parent, body.theme)}

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/",
                        max_age=auth.SESSION_HOURS * 3600)


def _account_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    role = conn.execute("SELECT id, name, is_owner FROM roles WHERE id = ?", (row["role_id"],)).fetchone()
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"],
            "role_id": row["role_id"], "role": role["name"] if role else None,
            "is_owner": bool(role["is_owner"]) if role else False,
            "person_id": row["person_id"], "disabled": bool(row["disabled"]),
            "permissions": sorted(roles.permissions_for(conn, row))}


def _device_password(value: str | None, required: bool) -> str | None:
    value = (value or "").strip()
    if not value:
        if required:
            raise HTTPException(400, "A Super Admin needs a 1 to 8 digit keypad password.")
        return None
    if not (value.isdigit() and 1 <= len(value) <= 8):
        raise HTTPException(400, "The keypad password must be 1 to 8 digits.")
    return value
