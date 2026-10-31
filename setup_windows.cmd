@echo off
setlocal
cd /d "%~dp0"
echo ScoutAI setup - Python 3.12, 64-bit recommended.
echo Setup installs packages only. It does not run AI research.
py -3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 goto try_python
set "SCOUTAI_SETUP_PYTHON=py -3.12"
goto python_ready
:try_python
python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 goto missing_python
set "SCOUTAI_SETUP_PYTHON=python"
:python_ready
if exist ".venv" if not exist ".venv\Scripts\python.exe" goto incompatible_env
if exist ".venv\Scripts\python.exe" goto install
%SCOUTAI_SETUP_PYTHON% -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32 else 1)"
if errorlevel 1 goto incompatible_env
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
if not exist "scoutai.local.toml" copy /y "scoutai.local.example.toml" "scoutai.local.toml" >nul
if not exist "scoutai.local.toml" goto failed
echo.
echo Setup complete. Double-click start_windows.cmd to open ScoutAI.
echo No API key is needed for the catalog, profiles or manual metrics.
pause
exit /b 0
:missing_python
echo Python 3.12 was not found. Install the 64-bit Windows version from python.org.
echo Enable the Python launcher and Add Python to PATH, then try again.
pause
exit /b 1
:incompatible_env
echo Existing .venv is incompatible. Rename only .venv and run setup again.
echo Keep your data folder and scoutai.local.toml unchanged.
pause
exit /b 1
:failed
echo Setup failed. Read the error above. Your database was not removed.
echo Check your Internet connection for package installation, then run setup again.
pause
exit /b 1
