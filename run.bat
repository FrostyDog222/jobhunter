@echo off
cd /d "%~dp0"

rem Starts the app. Installing things is FirstTimeSetup.bat's job - this checks that the setup
rem is there and hands over if it is not, rather than quietly doing a second, different install.

if not exist app.py (
  echo Unzip the whole folder first, then double-click run.bat from inside it.
  pause
  exit /b 1
)

rem Is the environment usable? A venv copied from another PC cannot run: its scripts point at
rem that PC's Python, so "the folder exists" proves nothing and the interpreter has to answer.
set READY=1
.venv\Scripts\python.exe -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if errorlevel 1 set READY=
if defined READY .venv\Scripts\python.exe -c "import fastapi, uvicorn, httpx, jinja2, playwright, python_multipart, pypdf, docx" >nul 2>&1
if errorlevel 1 set READY=
if defined READY goto :start

echo.
echo   This copy has not been set up on this PC yet.
echo.
if exist .venv echo   ^(There is a .venv folder, but it came from another PC and cannot run here.^)
echo   FirstTimeSetup.bat installs everything needed - Python included. It takes a
echo   few minutes, once.
echo.
if not exist FirstTimeSetup.bat (
  echo   FirstTimeSetup.bat is missing from this folder. Re-download the app.
  pause
  exit /b 1
)
choice /c YN /n /m "   Run FirstTimeSetup.bat now? [Y/N] "
if errorlevel 2 (
  echo.
  echo   Nothing was changed. Double-click FirstTimeSetup.bat when you are ready.
  pause
  exit /b 0
)
rem Full path, not the bare name: when NoDefaultCurrentDirectoryInExePath is set (group policy
rem on managed machines, and some security tools), cmd will not run a script from the current
rem directory by name - "if exist" finds it and "call" then says it does not exist.
call "%~dp0FirstTimeSetup.bat" /fromrun
rem Back here with everything installed - check once more, then start in this same window.
.venv\Scripts\python.exe -c "import fastapi, uvicorn, httpx, jinja2, playwright, python_multipart, pypdf, docx" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Setup did not finish. The error is above.
  pause
  exit /b 1
)
goto :start

:start
rem Keep the browser current: Playwright answers in about a second when the right build is
rem already there, and a folder check cannot tell a finished download from a half-finished one.
.venv\Scripts\python.exe -m playwright install chromium >nul 2>&1

rem A newer Python on the machine than the one this environment was built with is worth a word -
rem it is not a problem, but it is the usual reason an install starts behaving differently.
for /f "delims=" %%V in ('.venv\Scripts\python.exe -c "import sys;print('%%d.%%d'%%sys.version_info[:2])" 2^>nul') do set VENVPY=%%V
for /f "delims=" %%V in ('py -3 -c "import sys;print('%%d.%%d'%%sys.version_info[:2])" 2^>nul') do set SYSPY=%%V
if defined SYSPY if defined VENVPY if not "%SYSPY%"=="%VENVPY%" (
  echo Note: this PC now has Python %SYSPY%; the app is running on %VENVPY%.
  echo       Both work. To move it across, delete the .venv folder and run FirstTimeSetup.bat.
)

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
