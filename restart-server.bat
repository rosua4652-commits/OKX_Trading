@echo off
setlocal
cd /d "%~dp0"
title OKX Auto Trader Restart
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restart-server.ps1"
pause
endlocal
