@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo BTMH V5.4.10 - BUILD OFFLINE SETUP.EXE
echo ============================================================
set "PY="
where py >nul 2>nul && set "PY=py -3.12"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python 3.12 is required on the BUILD PC.
  pause
  exit /b 2
)
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo [ERROR] Inno Setup 6 is not installed on this BUILD PC.
  pause
  exit /b 4
)
if not exist "installer\output" mkdir "installer\output"
for /f "delims=" %%S in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "BUILD_STAMP=%%S"
set "STAGE=%CD%\dist\BTMH-Setup-Stage-%BUILD_STAMP%"
%PY% scripts\package_offline_bundle.py --stage "%STAGE%"
if errorlevel 1 exit /b 3
"%ISCC%" "/DBundleRoot=%STAGE%" "/DBuildStamp=%BUILD_STAMP%" "installer\CampusFace-V1.13.iss"
if errorlevel 1 exit /b 5
echo [OK] installer\output\BTMH_Setup_V5.4.10_%BUILD_STAMP%.exe
pause
