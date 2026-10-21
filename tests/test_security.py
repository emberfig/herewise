from fastapi.testclient import TestClient

from rollcall import auth
from rollcall.app import create_app


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_waits_double_after_five_misses_and_never_exceed_fifteen_minutes():
    clock = Clock()
    t = auth.LoginThrottle(clock)
    for _ in range(5):
        t.failed("lecturer")
    assert t.wait_seconds("lecturer") == 0                      # five are free
    t.failed("lecturer")
    assert t.wait_seconds("LECTURER ") == 30                     # same person however it is typed
    clock.now += 30
    t.failed("lecturer")
    assert t.wait_seconds("lecturer") == 60
    for _ in range(10):
        clock.now += 1000
        t.failed("lecturer")
    assert t.wait_seconds("lecturer") <= 15 * 60
    assert t.wait_seconds("someone-else") == 0                  # one name's misses do not slow another
    t.succeeded("lecturer")
    assert t.wait_seconds("lecturer") == 0


def test_throttle_forgets_misses_older_than_its_window():
    clock = Clock()
    t = auth.LoginThrottle(clock)
    for _ in range(5):
        t.failed("rep")
    clock.now += 16 * 60
    t.failed("rep")
    assert t.wait_seconds("rep") == 0


def test_login_is_slowed_the_same_for_real_and_unknown_usernames(tmp_path):
    with TestClient(create_app(tmp_path / "s.db")) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr", "password": "secret123",
                                   "academic_session": "2026/2027"})
        c.post("/api/logout")
        for name in ("lecturer", "nobody"):
            codes = [c.post("/api/login", json={"username": name, "password": "wrong"}).status_code
                     for _ in range(7)]
            assert codes == [401] * 6 + [429]
        blocked = c.post("/api/login", json={"username": "lecturer", "password": "secret123"})
        # While the wait runs even the right password is not checked, so it cannot be used to guess.
        assert blocked.status_code == 429 and "Wait" in blocked.json()["error"]
        assert int(blocked.headers["Retry-After"]) > 0


def test_every_response_carries_the_security_headers(tmp_path):
    with TestClient(create_app(tmp_path / "h.db")) as c:
        api = c.get("/api/setup/status")
        assert api.headers["Cache-Control"] == "no-store"
        # An asset revalidates rather than being kept: an upgraded Herewise running last version's
        # JavaScript out of the browser cache is invisible to everyone.
        assert c.get("/index.html").headers["Cache-Control"] == "no-cache"
        for response in (api, c.get("/gallery/sheet.html")):
            assert response.status_code == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["X-Frame-Options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        assert "Content-Security-Policy" not in c.get("/docs").headers   # Swagger UI comes from a CDN
