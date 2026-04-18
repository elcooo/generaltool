@echo off
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or not in PATH.
  echo Install Python 3.11+ and run this file again.
  pause
  exit /b 1
)

python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Failed to install requirements.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8000"
python run_tool.py --host 127.0.0.1 --port 8000

endlocal

