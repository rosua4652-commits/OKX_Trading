@echo off
setlocal
cd /d "%~dp0"
title OKX Auto Trader - Restore Local
echo === Restore from last local commit (no git pull) ===
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore-local.ps1"
pause
