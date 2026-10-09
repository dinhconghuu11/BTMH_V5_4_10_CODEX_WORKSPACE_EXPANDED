@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo CampusFace V1.12.0 PostgreSQL Offline - SETUP AND START
echo One package / one setup / one start
echo ============================================================

if exist "runtime\venv\Scripts\python.exe" goto start_now
if exist ".venv\Scripts\python.exe" goto start_now

rem Prefer an already installed, verified Python 3.12. This avoids invoking the
rem Python installer in maintenance mode on machines that already have Python.
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && goto online_setup
python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && goto online_setup

if exist "vendor\python-3.12.10-amd64.exe" if exist "vendor\wheels\*.whl" if exist "vendor\postgresql\postgresql-17.11-3-windows-x64-binaries.zip" if exist "models\face_detection_yunet_2023mar.onnx" if exist "models\face_recognition_sface_2021dec.onnx" goto offline_setup

echo [STOP] No installed runtime and this source folder is not a prepared offline bundle.
echo.
echo For a clean OFFLINE customer PC:
echo   1. On one Windows build PC with Internet run PREPARE_PORTABLE_OFFLINE_WINDOWS.bat
echo   2. Run BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat
echo   3. Copy that prepared ZIP to the customer PC
echo   4. Run this SETUP_AND_START_CAMPUSFACE_WINDOWS.bat again
echo.
echo For this PC with Internet, install Python 3.12 then run this file again.
pause
exit /b 2

:offline_setup
echo [MODE] Prepared offline package detected.
set "CAMPUSFACE_CHAINED=1"
call INSTALL_CAMPUSFACE_V1_WINDOWS.bat
if errorlevel 1 exit /b %ERRORLEVEL%
goto start_now

:online_setup
echo [MODE] Verified local Python 3.12 detected. Local offline wheels will be preferred when available.
set "CAMPUSFACE_CHAINED=1"
call INSTALL_CURRENT_PC_WINDOWS.bat
if errorlevel 1 exit /b %ERRORLEVEL%
goto start_now

:start_now
call START_CAMPUSFACE.bat
