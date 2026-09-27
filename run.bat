@echo off
cd /d "%~dp0"

rem Double-clicking run.bat inside the zip runs it from a temp folder with nothing beside it.
if not exist app.py (
  echo Unzip the whole folder first, then double-click run.bat from inside it.
  pause
  exit /b 1
)

rem Each setup step is gated on its OWN result. Gating all of them on the venv folder meant that
rem a failed install was never retried, and a venv copied from another PC - which cannot run,
rem because it points at that PC's Python - was taken for a working one.
.venv\Scripts\python.exe -c "import sys" >nul 2>&1
if not errorlevel 1 goto :deps

if exist .venv (
  echo The Python environment in this folder came from another PC. Rebuilding it...
  rmdir /s /q .venv
) else (
  echo First run - creating the Python environment...
)
if exist .env (
  echo.
  echo NOTE: this folder already holds API keys and job-board sign-ins.
  echo       If they are not yours, close this window and delete these first:
  echo       .env  .session.json  .boards.json  profile.json  settings.json  db.sqlite  out
  echo.
)

rem The py launcher first - it is there even when "Add to PATH" was not ticked - then python.
set PY=
py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if not errorlevel 1 set PY=py -3
if defined PY goto :venv
python -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if not errorlevel 1 set PY=python
if not defined PY goto :nopython

:venv
%PY% -m venv .venv
if errorlevel 1 goto :fail

:deps
.venv\Scripts\python.exe -c "import fastapi, uvicorn, httpx, jinja2, playwright, python_multipart, pypdf, docx" >nul 2>&1
if not errorlevel 1 goto :browser
echo Installing dependencies, this takes a few minutes...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail

:browser
rem Always ask: it answers in about a second when the right browser build is already there,
rem and a folder check cannot tell a finished download from a half-finished one.
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :fail

echo.
echo Starting - keep this window open. Closing it stops the app.
echo Dashboard: http://127.0.0.1:8777  (opens by itself in a moment)
echo First time? The dashboard walks you through it: AI key, profile, first search.
echo.
set JOB_OPEN=1
.venv\Scripts\python.exe app.py

rem Anything the app raises used to close this window instantly, taking the error with it.
echo.
echo The app has stopped. Any error is printed above.
pause
goto :eof

:nopython
echo.
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
goto :eof

:fail
echo.
echo Setup failed - see the error above. Check your internet connection, then run run.bat again.
pause
