@echo off
setlocal
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed or not in PATH.
  pause
  exit /b 1
)

python -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Failed to install build dependencies.
  pause
  exit /b 1
)

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist ReplayTool.spec del /q ReplayTool.spec

pyinstaller ^
  --onefile ^
  --name ReplayTool ^
  --add-data "replay_tool\\id_lookup.json;replay_tool" ^
  run_tool.py

if errorlevel 1 (
  echo EXE build failed.
  pause
  exit /b 1
)

echo.
echo Build complete: dist\\ReplayTool.exe
echo Send dist\\ReplayTool.exe to someone. They can double-click it to run.
pause
endlocal

