@echo off
setlocal
cd /d "%~dp0"
title OKX Auto Trader Log
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" -Log
pause
endlocal
