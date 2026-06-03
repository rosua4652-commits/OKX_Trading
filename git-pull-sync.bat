@echo off
setlocal
cd /d "%~dp0"
title OKX Git Pull Sync
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\git-pull-sync.ps1"
pause
endlocal
