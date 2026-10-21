"""Screen 40, About: the version, and every licence read from the packages themselves.

The route had no test until the packaged build showed it could lose rows silently: a build carries
almost no package metadata unless told to, and a missing package is skipped rather than reported.
packaging/build.py now refuses a build that would do that; these cover the route and the reading.
"""
from email.message import Message

import pytest
from fastapi.testclient import TestClient

from rollcall import NAME, VERSION, about
from rollcall.app import create_app


@pytest.fixture
def client(tmp_path, k40_factory):
    app = create_app(tmp_path / "about.db", k40_factory=k40_factory)
    with TestClient(app) as c:
        c.post("/api/setup", json={"username": "lecturer", "display_name": "Dr Lecturer",
                                   "password": "secret123", "academic_session": "2026/2027"})
        yield c


def test_about_states_the_version_and_the_licence_that_decides_herewises_own(client):
    body = client.get("/api/about").json()
    assert (body["name"], body["version"], body["studio"]) == (NAME, VERSION, "Emberfig")
    rows = {p["name"]: p for p in body["packages"]}
    assert rows["pyzk"]["licence"] == "GNU GPL version 2"
    assert "GNU General Public License version 2" in body["licence_note"]
    # Everything the list names is installed wherever the suite runs, so every row is present.
    assert list(rows) == [name for name, _ in about.PACKAGES]
    assert all(p["version"] and p["licence"] and p["why"] for p in body["packages"])
    assert {f["licence"] for f in body["fonts"]} == {"SIL Open Font License 1.1"}


def meta(**fields):
    message = Message()
    for key, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            message[key.replace("_", "-")] = item
    return message


def test_a_licence_is_read_from_the_most_trustworthy_place_the_package_states_it():
    assert about.licence_of("x", meta(License_Expression="MIT", License="BSD")) == "MIT"
    assert about.licence_of("x", meta(Classifier=["Programming Language :: Python",
                                                  "License :: OSI Approved :: BSD License"])) == "BSD"
    assert about.licence_of("x", meta(License="Apache 2.0")) == "Apache 2.0"
    # A filename, or a whole licence pasted into the field, says nothing on a screen.
    assert about.licence_of("x", meta(License="LICENSE.txt")) == "stated in the package's own files"
    assert about.licence_of("x", meta(License="Permission is hereby granted " * 5)) == \
        "stated in the package's own files"
    assert about.licence_of("pyzk", meta(License="LICENSE.txt")) == "GNU GPL version 2"
