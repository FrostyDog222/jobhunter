@echo off
title jobhunter - first time setup
cd /d "%~dp0"
color 0F

rem run.bat calls this with /fromrun when the app is not set up yet: same work, no second
rem round of questions, and it goes back there to start the app in the same window.
set FROMRUN=
if /i "%~1"=="/fromrun" set FROMRUN=1

echo.
echo   ==========================================
echo      jobhunter  -  first time setup
echo   ==========================================
echo.
echo   This installs everything the app needs:
echo.
echo     1. Python            - the language it is written in
echo     2. Its packages      - the web server, the PDF reader, the browser driver
echo     3. Chromium          - a browser it uses to read job pages and make PDFs
echo.
echo   You only do this once. It takes about five minutes on a new PC,
echo   and needs an internet connection. Nothing of yours is sent anywhere.
echo.
if not defined FROMRUN pause
echo.

if not exist app.py (
  echo   [X] This script is not next to the app.
  echo       Unzip the whole folder first, then run FirstTimeSetup.bat from inside it.
  goto :done
)

rem ---------------------------------------------------------------- 1. Python
echo   [1/4] Looking for Python...
call :findpython
if defined PY goto :havepython

echo         Not installed. Getting it now - this is the slow part.
echo.
rem winget ships with Windows 11 and is the tidiest way in.
where winget >nul 2>&1
if not errorlevel 1 (
  echo         Installing Python through the Windows package manager...
  winget install -e --id Python.Python.3.12 --scope user --silent ^
    --accept-package-agreements --accept-source-agreements
  call :findpython
)
if defined PY goto :havepython

rem No winget, or it did not work: take the installer straight from python.org.
echo         Downloading the installer from python.org...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'" ^
  " -OutFile \"$env:TEMP\jobhunter-python.exe\" -UseBasicParsing"
if errorlevel 1 (
  echo   [X] Could not download Python. Check your internet connection and run this again.
  goto :done
)
echo         Installing Python. A progress window may appear - let it finish.
"%TEMP%\jobhunter-python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1
del "%TEMP%\jobhunter-python.exe" >nul 2>&1
call :findpython
if not defined PY (
  echo.
  echo   [X] Python was installed but this window cannot see it yet.
  echo       Close this window, open the folder again and run FirstTimeSetup.bat once more.
  goto :done
)

:havepython
for /f "delims=" %%V in ('%PY% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set PYVER=%%V
echo         Python %PYVER% - ok
echo.

rem ---------------------------------------------------------------- 2. the environment
echo   [2/4] Building the app's own Python environment...
.venv\Scripts\python.exe -c "import sys" >nul 2>&1
if not errorlevel 1 goto :haveenv
if exist .venv (
  echo         The existing one came from another PC. Rebuilding it.
  rmdir /s /q .venv
)
%PY% -m venv .venv
if errorlevel 1 (
  echo   [X] Could not create the environment. The error is above.
  goto :done
)
:haveenv
echo         ok
echo.

rem ---------------------------------------------------------------- 3. packages
echo   [3/4] Installing the app's packages...
.venv\Scripts\python.exe -m pip install -q --upgrade pip >nul 2>&1
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo   [X] Installing the packages failed. The error is above.
  echo       The usual cause is no internet, or antivirus blocking pip.
  goto :done
)
echo         ok
echo.

rem ---------------------------------------------------------------- 4. browser
echo   [4/4] Installing Chromium for the app...
.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
  echo   [X] Installing the browser failed. The error is above.
  goto :done
)
echo         ok
echo.

rem ---------------------------------------------------------------- check it all works
echo   Checking that everything actually works...
.venv\Scripts\python.exe -c "import fastapi, uvicorn, httpx, jinja2, playwright, python_multipart, pypdf, docx" 2>nul
if errorlevel 1 (
  echo   [X] Something did not install. Run FirstTimeSetup.bat once more.
  goto :done
)
.venv\Scripts\python.exe test_app.py
if errorlevel 1 (
  echo.
  echo   [!] The packages are installed, but the self-check did not pass.
  echo       The app will probably still start. The error is above.
  goto :finish
)

:finish
echo.
echo   ==========================================
echo      Setup finished.
echo   ==========================================
echo.
echo   From now on, start the app by double-clicking  run.bat
echo.
rem Called from run.bat: it does the starting, and asking twice would be silly.
if defined FROMRUN exit /b 0
echo   The dashboard will walk you through the three things left to do:
echo     - choose an AI model and paste its key  (there are free ones)
echo     - upload your CV so it knows your history
echo     - run your first search
echo.
choice /c YN /n /m "   Start it now? [Y/N] "
if errorlevel 2 goto :done
start "" "%~dp0run.bat"
exit /b 0

:done
echo.
pause
exit /b 0

rem ------------------------------------------------------------------------
rem Find a Python 3.10+ we can use. The py launcher first, because it works
rem even when "Add to PATH" was never ticked, then PATH, then the two places
rem the installer actually puts it - PATH is not refreshed inside a window
rem that was already open when Python was installed.
:findpython
set PY=
py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if not errorlevel 1 set PY=py -3
if defined PY goto :eof
python -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if not errorlevel 1 set PY=python
if defined PY goto :eof
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do call :trypy "%%D\python.exe"
if defined PY goto :eof
for /d %%D in ("%ProgramFiles%\Python3*") do call :trypy "%%D\python.exe"
goto :eof

:trypy
if defined PY goto :eof
if not exist %1 goto :eof
%1 -c "import sys; sys.exit(sys.version_info[:2] < (3,10))" >nul 2>&1
if not errorlevel 1 set PY=%1
goto :eof
