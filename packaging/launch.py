"""What the packaged Herewise.exe runs.

    Herewise.exe                              opens the window
    Herewise.exe reset-password <username>    the sole owner's way back in (known gap 3)

A separate file from `rollcall/__main__.py`, which is the developer's entry point and starts a bare
server. PyInstaller needs a plain script to analyse, and this one must open a window, not a server.

The reset is here as well because the installed app is the only copy a lecturer has: before this it
worked only from a source checkout, so a sole owner who forgot their password needed somebody to
install Python. It runs against this computer's register, exactly as `python -m rollcall
reset-password` does, and writes the same audit row.
"""
import multiprocessing
import sys


def open_console() -> None:
    """A windowed build starts with no console, so the reset opens one of its own.

    Attaching to the console it was started from would be neater, but cmd and PowerShell do not wait
    for a windowed program, so both would read the same keyboard at once. getpass hides what is
    typed only when stdin is the process's original stdin, and a windowed build has none, so the new
    console becomes the original too; otherwise the password would be echoed as it was typed.
    """
    import ctypes
    ctypes.windll.kernel32.AllocConsole()
    ctypes.windll.kernel32.SetConsoleTitleW("Herewise: reset a password")
    conin = open("CONIN$", "r", encoding="utf-8")
    conout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    sys.stdin = sys.__stdin__ = conin
    sys.stdout = sys.__stdout__ = conout
    sys.stderr = sys.__stderr__ = conout


def reset_password(args: list[str]) -> int:
    open_console()
    if len(args) != 1:
        print("Usage: Herewise.exe reset-password <username>")
        code = 1
    else:
        from rollcall.__main__ import reset_password as reset
        code = reset(args[0])
    # The console closes with the process, so it waits until the result has been read.
    input("\nPress Enter to close this window.")
    return code


if __name__ == "__main__":
    # Without this a frozen build that ever spawns a process re-runs the whole app in the child.
    multiprocessing.freeze_support()
    if sys.argv[1:2] == ["reset-password"]:
        sys.exit(reset_password(sys.argv[2:]))
    from rollcall.window import run
    sys.exit(run())
