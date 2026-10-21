"""Where the database, backups and logs live, and which port the app listens on."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
PORT_TRIES = 20              # 8000 to 8019: another program on 8000 must not stop the register opening
APP_FOLDER = "Herewise"
PORTABLE_MARKER = "portable"  # a file with this name beside the executable keeps the data beside it


def data_dir() -> Path:
    """The data folder.

    Packaged, the installer puts the program in %LOCALAPPDATA%\\Programs\\Herewise, and installing
    or removing it replaces or deletes that whole folder. So the register lives in a folder of its
    own, %LOCALAPPDATA%\\Herewise, which no installer touches, which needs no administrator rights,
    and which is never synced (a database inside a OneDrive folder can be corrupted by the sync). A
    file named "portable" beside the executable keeps everything beside it instead, for a copy run
    from a USB stick. ROLLCALL_DATA_DIR overrides both.
    """
    override = os.environ.get("ROLLCALL_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent
        if (beside / PORTABLE_MARKER).exists():
            return beside
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / APP_FOLDER if local else Path.home() / APP_FOLDER
    return Path(__file__).resolve().parent.parent / "instance"


def default_db_path() -> Path:
    return data_dir() / "rollcall.db"


def free_port(host: str = HOST, first: int = PORT, tries: int = PORT_TRIES) -> int:
    """The first port from ``first`` that nothing is listening on."""
    for port in range(first, first + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"Ports {first} to {first + tries - 1} are all in use. Close another program and try again.")
