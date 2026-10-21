"""A log file in the data folder, so a fault seen on someone else's machine can be diagnosed later.

Rotating: at most five files of 1 MB each. The log records what the app did and what failed, never a
password or a keypad password: nothing in the app logs request bodies.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "herewise.log"


def configure(folder: Path) -> Path:
    folder = Path(folder) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    # The root catches the app's own loggers, which pass records up; uvicorn's do not, so they get it too.
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(getattr(h, "baseFilename", None) == str(path.resolve()) for h in logger.handlers):
            logger.addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).propagate = False
    return path
