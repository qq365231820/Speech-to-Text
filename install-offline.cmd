@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt faster-whisper opencc-python-reimplemented
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install llama-cpp-python --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if errorlevel 1 goto failed
echo Offline runtime installed. Download models using the links in README.md.
echo Then select the model folder and GGUF file in settings.
pause
exit /b 0
:failed
echo Installation failed. Download progress is preserved for retry.
pause
exit /b 1
