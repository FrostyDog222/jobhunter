@echo off
cd /d "%~dp0"
rem Packs a clean copy of the app for someone else. Your keys, profile, job list, board
rem sign-ins and generated CVs are left out - see share.py for the exact list.
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe share.py
) else (
  python share.py
)
echo.
pause
