@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo BTMH V5.4.10 - BUILD OFFLINE DEPLOYMENT ZIP
echo ============================================================
set "PY="
where py >nul 2>nul && set "PY=py -3.12"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python not found on this build computer.
  pause
  exit /b 2
)
set "NAME=BTMH-V5.4.10-Windows-x64-OFFLINE"
for /f "delims=" %%S in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%S"
set "NAME=%NAME%-%BUILD_STAMP%"
set "STAGE=%CD%\dist\%NAME%"
set "OUT=%CD%\dist\%NAME%.zip"
%PY% scripts\package_offline_bundle.py --stage "%STAGE%" --zip "%OUT%"
if errorlevel 1 exit /b 4
echo.
echo [OK] %OUT%
echo [NEXT] Copy this ZIP and its SHA256 to the offline target, Extract All, then run SETUP_OFFLINE_WINDOWS.bat as a standard user.
pause
