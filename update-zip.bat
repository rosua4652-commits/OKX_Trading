@echo off
setlocal
cd /d "%~dp0"
echo.
echo  ZIP update + npm build — keeps backend\data and .env
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\oat-update-zip.ps1" -RepoRoot "%CD%"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
