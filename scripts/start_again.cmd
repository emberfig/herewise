@echo off
rem Uninstall Herewise and remove its register, so the next install starts from nothing.
rem Run through Explorer, never from a terminal inside a packaged (MSIX) Windows app: such an app
rem redirects %LOCALAPPDATA% into its own package folder, so a delete run from inside it would leave
rem the real register exactly where it is and report success.
rem
rem     explorer.exe scripts\start_again.cmd
setlocal
cd /d "%~dp0.."
if "%HEREWISE_PYTHON%"=="" set HEREWISE_PYTHON=%LOCALAPPDATA%\rollcall-venv\Scripts\python.exe
if not exist "%HEREWISE_PYTHON%" for /d %%P in ("%LOCALAPPDATA%\Packages\*") do if exist "%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe" set "HEREWISE_PYTHON=%%P\LocalCache\Local\rollcall-venv\Scripts\python.exe"
if not exist "%HEREWISE_PYTHON%" (
  echo No interpreter found. Set HEREWISE_PYTHON to a Python on this machine.
  pause
  exit /b 3
)
"%HEREWISE_PYTHON%" scripts\start_again.py "%CD%\build\start-again.txt" > "build\start-again-console.txt" 2>&1
echo exit code %ERRORLEVEL% >> "build\start-again-console.txt"
type "build\start-again-console.txt"
