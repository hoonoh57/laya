@echo off
setlocal
cd /d "%~dp0"
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
if not exist .env (
  copy .env.example .env >nul
  echo [.env created] Fill in your keys, save, then run start.bat again.
  notepad .env
  exit /b
)
if not exist .venv\Scripts\pythonw.exe (echo .venv not found & pause & exit /b 1)
call "%~dp0stop.bat" /quiet
if not exist logs mkdir logs
start "" /b .venv\Scripts\pythonw.exe -m laya_trader
powershell -NoProfile -ExecutionPolicy Bypass -File tools\wait_health.ps1
if errorlevel 1 (echo Start failed - check logs\server.log & pause & exit /b 1)
echo Server running. Close this window anytime; use stop.bat to stop.
timeout /t 3 >nul
