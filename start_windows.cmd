@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing_env
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 goto missing_env
".venv\Scripts\python.exe" run_local.py
if errorlevel 1 goto failed
exit /b 0
:missing_env
echo Run setup_windows.cmd first. Python 3.12 is required.
pause
exit /b 1
:failed
echo ScoutAI could not start. Read the error above.
echo If it is already running, open http://127.0.0.1:8501 in your browser.
pause
exit /b 1
