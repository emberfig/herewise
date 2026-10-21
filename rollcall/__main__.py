"""Run the app: python -m rollcall

One other command, for the case the app itself cannot answer:

    python -m rollcall reset-password <username>

That is the way back in for the only owner when they have forgotten their password (known gap 3).
Everyone else is reset from the Accounts screen by somebody whose role allows managing accounts;
the sole owner has nobody above them. It runs on this computer, against this computer's database,
so it needs the same access as copying the database file would, and it writes an audit row.
"""
import getpass
import logging
import sys

import uvicorn

from . import auth, db, logs
from .app import create_app
from .config import HOST, data_dir, default_db_path, free_port


def serve() -> None:
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    log_file = logs.configure(folder)
    port = free_port()
    log = logging.getLogger("rollcall")
    log.info("Starting on http://%s:%s with data in %s (log: %s)", HOST, port, folder, log_file)
    print(f"Herewise is running at http://{HOST}:{port}  (data: {folder})", flush=True)
    # Local only. Binding to 127.0.0.1 keeps the register off the university network.
    uvicorn.run(create_app(), host=HOST, port=port, log_level="info", log_config=None)


def reset_password(username: str) -> int:
    path = default_db_path()
    if not path.exists():
        print(f"No register at {path}.")
        return 1
    conn = db.connect(path)
    try:
        row = conn.execute("SELECT id, username, display_name FROM accounts WHERE username = ?",
                           (username,)).fetchone()
        if row is None:
            names = [r["username"] for r in conn.execute("SELECT username FROM accounts ORDER BY id")]
            print(f"No account called {username}. This register has: {', '.join(names) or 'none'}.")
            return 1
        print(f"Setting a new password for {row['display_name']} ({row['username']}) in {path}.")
        password = getpass.getpass("New password: ")
        again = getpass.getpass("Type it again: ")
        if password != again:
            print("Those did not match. Nothing was changed.")
            return 1
        with db.transaction(conn):
            auth.set_password(conn, row["id"], password)
            # Recorded like any other reset, so the log shows it happened and how.
            db.audit(conn, row["id"], "account.password", "accounts", row["id"],
                     f"{row['username']}, reset from the command line on this computer")
        print("Done. Every session that account had is ended, so sign in again.")
        return 0
    except ValueError as exc:
        print(str(exc))
        return 1
    finally:
        conn.close()


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "reset-password":
        if len(args) != 2:
            print("Usage: python -m rollcall reset-password <username>")
            raise SystemExit(1)
        raise SystemExit(reset_password(args[1]))
    serve()


if __name__ == "__main__":
    main()
