@echo off
setlocal
cd /d "%~dp0"
title OKX Auto Trader Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-server.ps1"
pause
endlocal
