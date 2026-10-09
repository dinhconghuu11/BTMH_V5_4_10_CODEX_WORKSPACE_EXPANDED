@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo BTMH V5.4.10 - PREPARE FULL OFFLINE CUSTOMER BUNDLE
 echo Python + PostgreSQL + AI models + all wheels
 echo Run this ONCE on a Windows build PC WITH Internet.
echo ============================================================
set "PY="
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && set "PY=py -3.12"
if not defined PY python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python 3.12 is required on the BUILD computer.
  pause
  exit /b 2
)
if not exist "vendor\wheels" mkdir "vendor\wheels"
if not exist "models" mkdir "models"
echo [1/5] Downloading Windows Python wheels ...
%PY% -m pip download --index-url https://pypi.org/simple -r requirements-runtime.txt -d "vendor\wheels" --only-binary=:all: --platform win_amd64 --python-version 312 --implementation cp --abi cp312
if errorlevel 1 exit /b 3
echo [1B/5] Downloading V2.8 WebRTC media wheels ...
%PY% -m pip download --index-url https://pypi.org/simple -r requirements-media.txt -d "vendor\wheels" --only-binary=:all: --platform win_amd64 --python-version 312 --implementation cp --abi cp312
if errorlevel 1 exit /b 3
echo [2/5] Downloading verified FaceID and Passive PAD models into the bundle ...
set "CAMPUSFACE_DATA_ROOT=%CD%"
%PY% scripts\download_models.py
if errorlevel 1 exit /b 4
echo [3/5] Downloading Python 3.12.10 installer ...
if not exist "vendor\python-3.12.10-amd64.exe" powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile 'vendor\python-3.12.10-amd64.exe'"
if errorlevel 1 exit /b 5
echo [4/5] Downloading PostgreSQL 17.11 embedded binary runtime ...
call PREPARE_POSTGRESQL_OFFLINE_WINDOWS.bat
if errorlevel 1 exit /b 6
echo [5/5] Import the verified MediaMTX v1.21.1 ZIP and acquisition/license evidence ...
echo Required: vendor\mediamtx\mediamtx_v1.21.1_windows_amd64.zip
echo SHA256: faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23
echo See OFFLINE_DEPLOYMENT.md for official URL, USB import and redistribution evidence.
%PY% scripts\validate_portable_bundle.py
if errorlevel 1 exit /b 7
echo.
echo [OK] Offline payload audit passed. Build still requires separate production acceptance.
echo [NEXT] BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat
pause
