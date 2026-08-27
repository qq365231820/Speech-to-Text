@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installed. Run start.cmd.
pause
exit /b 0
:failed
echo Installation failed. Check Python 3.10+ and your network.
pause
exit /b 1
