@echo off
cd /d "%~dp0"

rem A previous update left a newer copy of this file: swap it in before doing anything else.
rem cmd reads a batch file line by line as it runs, so a script cannot safely overwrite itself.
if exist "Update.bat.new" (
  move /y "Update.bat.new" "Update.bat" >nul
  echo   The updater itself was updated. Starting it again...
  call "%~dp0Update.bat"
  exit /b 0
)

if not exist update.py (
  echo   update.py is missing from this folder. Re-download the app.
  pause
  exit /b 1
)

rem The app's own Python if the setup has been run, otherwise whatever is on the machine -
rem updating should still work on a copy that was never set up.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" update.py
) else (
  py -3 update.py 2>nul || python update.py
)
