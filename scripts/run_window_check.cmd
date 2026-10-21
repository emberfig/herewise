@echo off
rem Check the packaged window OUTSIDE any packaged (MSIX) Windows app, which redirects
rem %LOCALAPPDATA% and so proves nothing about where anything really lands. Start it from
rem Explorer, not from a terminal inside such an app:
rem
rem     explorer.exe scripts\run_window_check.cmd
rem
rem This runs steps 3 and 4 of the install acceptance only: the built app starts, and pressing
rem Download a backup in its own window reaches Windows' own Save dialog. It installs nothing,
rem uninstalls nothing and never opens a real register, so it is safe on a machine that already has
rem somebody's Herewise on it. The full run is scripts\run_install_acceptance.cmd, which does all
rem three and needs a machine with no Herewise installed and no register to lose.
rem
rem HEREWISE_PYTHON overrides the interpreter, which is what a session inside that app needs,
rem because its venv is under the package folder rather than at the path it appears to be at.
setlocal
cd /d "%~dp0.."
rem A venv made from inside a packaged app really lives under that app's own package folder. A
rem session inside the app sees it at the plain path; a process Explorer starts does not, so the
rem package folders are searched for it.
if "%HEREWISE_PYTHON%"=="" set HEREWISE_PYTHON=%LOCALAPPDATA%\rollcall-venv\Scripts\python.exe
if not exist "%HEREWISE_PYTHON%" for /d %%P in ("%LOCALAPPDATA%\Packages\*") do if exist "%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe" set "HEREWISE_PYTHON=%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe"
if not exist "%HEREWISE_PYTHON%" (
  echo No interpreter found. Set HEREWISE_PYTHON to a Python with requirements-dev.txt installed.
  pause
  exit /b 3
)
echo LOCALAPPDATA is %LOCALAPPDATA%
echo Python is %HEREWISE_PYTHON%
"%HEREWISE_PYTHON%" scripts\install_acceptance.py --window-only > "build\window-check-console.txt" 2>&1
echo exit code %ERRORLEVEL% >> "build\window-check-console.txt"
type "build\window-check-console.txt"
