"""The app window's settings. The window itself needs a desktop to open, so what is tested here is
what Herewise asks of pywebview, against pywebview's own settings object where it is installed.

The first packaged build left pywebview's default in place, which cancels every download: the
backup, the sheet, the eligibility list and every CSV did nothing when pressed, with no message.
"""
import pytest

from rollcall import window


class FakeWebview:
    def __init__(self):
        self.settings = {"ALLOW_DOWNLOADS": False, "OPEN_EXTERNAL_LINKS_IN_BROWSER": False}


def test_the_window_allows_downloads_and_sends_links_out_to_the_browser():
    fake = FakeWebview()
    window.configure(fake)
    assert fake.settings == {"ALLOW_DOWNLOADS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": True}


def test_the_settings_exist_in_the_pywebview_that_ships():
    # pywebview's settings refuse new keys, so a renamed setting in an upgrade fails here, not in a
    # lecturer's window.
    webview = pytest.importorskip("webview")
    before = dict(webview.settings)
    try:
        window.configure(webview)
        assert webview.settings["ALLOW_DOWNLOADS"] is True
        assert webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
    finally:
        for key, value in before.items():
            webview.settings[key] = value
