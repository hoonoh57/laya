@echo off
setlocal
cd /d "%~dp0"
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
set Q=
if /i "%~1"=="/quiet" set Q=-Quiet
powershell -NoProfile -ExecutionPolicy Bypass -File tools\stop.ps1 %Q%
if not defined Q (echo Stopped. & timeout /t 3 >nul)
