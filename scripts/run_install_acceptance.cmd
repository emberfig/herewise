@echo off
rem Run the install acceptance OUTSIDE any packaged (MSIX) Windows app, which redirects
rem %LOCALAPPDATA% and so proves nothing about where an install really lands. Start it from
rem Explorer, not from a terminal inside such an app:
rem
rem     explorer.exe scripts\run_install_acceptance.cmd
rem
rem A process Explorer starts is outside the app's container: checked on 2026-09-21 with a marker
rem file written to %LOCALAPPDATA% from inside the app, which a run started this way cannot see.
rem
rem HEREWISE_PYTHON overrides the interpreter, which is what a session inside that app needs,
rem because its venv is under the package folder rather than at the path it appears to be at.
setlocal
cd /d "%~dp0.."
if "%HEREWISE_PYTHON%"=="" set HEREWISE_PYTHON=%LOCALAPPDATA%\rollcall-venv\Scripts\python.exe
rem A venv made from inside a packaged app really lives under that app's package folder, and a
rem process Explorer starts does not see it at the plain path, so look for it there.
if not exist "%HEREWISE_PYTHON%" for /d %%P in ("%LOCALAPPDATA%\Packages\*") do if exist "%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe" set "HEREWISE_PYTHON=%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe"
if not exist "%HEREWISE_PYTHON%" (
  echo No interpreter found. Set HEREWISE_PYTHON to a Python with requirements-dev.txt installed.
  pause
  exit /b 3
)
echo LOCALAPPDATA is %LOCALAPPDATA%
"%HEREWISE_PYTHON%" scripts\install_acceptance.py %* > "build\install-acceptance-console.txt" 2>&1
echo exit code %ERRORLEVEL% >> "build\install-acceptance-console.txt"
type "build\install-acceptance-console.txt"
