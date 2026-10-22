"""System, Light or Dark, chosen on this computer (asked for on 2026-10-22)."""
import re
import zipfile
from datetime import datetime
from io import BytesIO

from fastapi.testclient import TestClient

from test_live import a_course, client, fresh_terminal_memory, scan  # noqa: F401 (fixtures)
from rollcall import appearance, db

STATIC = appearance._TOKENS.parent.parent


def setup(client):
    client.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                    "password": "secret123", "academic_session": "2026/2027"})


def test_a_new_computer_follows_windows(client):
    assert client.get("/api/appearance").json()["theme"] == "system"
    script = client.get("/api/appearance.js")
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    # System sets no data-theme, which leaves the tokens' prefers-color-scheme rule in charge.
    assert "dataset.theme" not in script.text
    assert 'dataset.appearance = "system"' in script.text


def test_the_choice_is_kept_and_the_page_is_told_before_it_paints(client):
    setup(client)
    assert client.put("/api/appearance", json={"theme": "dark"}).json() == {"theme": "dark"}
    script = client.get("/api/appearance.js")
    assert 'dataset.theme = "dark"' in script.text
    # Never from a cache: a choice changed in one window would otherwise come back on the next load.
    assert script.headers["cache-control"] == "no-store"
    assert client.put("/api/appearance", json={"theme": "light"}).status_code == 200
    assert 'dataset.theme = "light"' in client.get("/api/appearance.js").text


def test_the_page_runs_the_script_before_any_stylesheet():
    """A module script waits for the document; only a classic one in the head runs before paint."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = html.index('<script src="/api/appearance.js"></script>')
    assert script < html.index('<link rel="stylesheet"')
    assert 'type="module" src="/api/appearance.js"' not in html


def test_only_the_three_choices_are_taken(client):
    setup(client)
    assert client.put("/api/appearance", json={"theme": "sepia"}).status_code == 422
    assert client.get("/api/appearance").json()["theme"] == "system"


def test_setup_can_choose_before_any_account_but_afterwards_only_someone_signed_in(client):
    assert client.put("/api/appearance", json={"theme": "dark"}).status_code == 200, "setup offers it"
    setup(client)
    with TestClient(client.app) as stranger:
        refused = stranger.put("/api/appearance", json={"theme": "light"})
        assert refused.status_code == 401
    assert client.get("/api/appearance").json()["theme"] == "dark"


def test_any_role_may_choose_since_it_changes_nothing_in_the_register(client):
    setup(client)
    viewer = next(r["id"] for r in client.get("/api/roles").json() if r["name"] == "Viewer")
    client.post("/api/accounts", json={"username": "viewer", "display_name": "A Viewer",
                                       "password": "secret123", "role_id": viewer})
    with TestClient(client.app) as theirs:
        theirs.post("/api/login", json={"username": "viewer", "password": "secret123"})
        assert theirs.put("/api/appearance", json={"theme": "dark"}).status_code == 200
    log = client.get("/api/audit").json()["entries"]
    assert not any("appearance" in (e["action"] or "") for e in log)


def test_it_is_kept_beside_the_register_not_in_it(client):
    """The register moves with Download your data and comes back with a restore; this computer's
    choice does neither."""
    setup(client)
    client.put("/api/appearance", json={"theme": "dark"})
    folder = client.db_path.parent
    assert appearance.read(folder) == "dark"
    conn = db.connect(client.db_path)
    stored = [tuple(r) for r in conn.execute("SELECT key, value FROM settings WHERE value = 'dark'")]
    conn.close()
    assert stored == []


def test_a_damaged_choice_reads_as_system(tmp_path):
    (tmp_path / appearance.FILE).write_text("{not json", encoding="utf-8")
    assert appearance.read(tmp_path) == "system"
    (tmp_path / appearance.FILE).write_text('{"theme": "neon"}', encoding="utf-8")
    assert appearance.read(tmp_path) == "system"
    assert appearance.read(tmp_path / "nothing here") == "system"


def test_the_window_opens_on_the_paper_of_the_theme_it_is_about_to_draw():
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    light = re.search(r":root \{\s*--hw-paper: (#\w{6})", tokens).group(1)
    dark = re.search(r':root\[data-theme="dark"\], \[data-theme="dark"\] \{\s*--hw-paper: (#\w{6})', tokens).group(1)
    assert appearance.paper() == {"light": light, "dark": dark}
    assert appearance.window_background("light", prefers_dark=lambda: True) == light
    assert appearance.window_background("dark", prefers_dark=lambda: False) == dark
    assert appearance.window_background("system", prefers_dark=lambda: True) == dark
    assert appearance.window_background("system", prefers_dark=lambda: False) == light


def test_exports_are_the_same_whichever_is_chosen(client, fake):
    course, students = a_course(client)
    class_id = client.post(f"/api/courses/{course['id']}/live").json()["register"]["session"]["id"]
    scan(fake, students[0], datetime.now())
    client.post(f"/api/live/{class_id}/end", json={})
    template_id = client.get(f"/api/courses/{course['id']}").json()["template_id"]

    def workbook():
        xlsx = client.get(f"/api/templates/{template_id}/export?format=xlsx")
        assert xlsx.status_code == 200
        with zipfile.ZipFile(BytesIO(xlsx.content)) as book:
            # Everything a reader sees: the cells and their styles. Not the file's own timestamps.
            return {name: book.read(name) for name in book.namelist()
                    if name.startswith("xl/") and "docProps" not in name}

    client.put("/api/appearance", json={"theme": "light"})
    light = workbook()
    client.put("/api/appearance", json={"theme": "dark"})
    assert workbook() == light
    pdf = client.get(f"/api/templates/{template_id}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
