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
echo [1/2] stopping old server/bridge...
call "%~dp0stop.bat" /quiet
echo [2/2] starting server...
powershell -NoProfile -ExecutionPolicy Bypass -File tools\launch.ps1
if errorlevel 1 (pause & exit /b 1)
echo Server running. Use stop.bat to stop.
timeout /t 3 >nul
