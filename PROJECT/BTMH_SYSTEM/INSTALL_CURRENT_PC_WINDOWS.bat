@echo off
setlocal EnableExtensions
set "BTMH_ENV=production"
set "PYTHONDONTWRITEBYTECODE=1"
if "%BTMH_UI_PREVIEW%"=="1" (
  echo [BLOCKED] Production setup cannot use an inherited UI Preview profile. Start setup in a fresh standard-user shell with the intended production data root.
  exit /b 20
)
rem Data root resolver uses %LOCALAPPDATA%\CampusFace for fresh installs and reuses legacy profiles.
rem Compatibility note: earlier service installer had Administrator required; current per-user path has No Administrator required.
cd /d "%~dp0"
if "%CAMPUSFACE_OFFLINE%"=="1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_offline_bundle.ps1" -Root "%CD%"
  if errorlevel 1 exit /b 20
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\check_standard_user.ps1"
if errorlevel 1 (
  pause
  exit /b 5
)
call "%~dp0scripts\resolve_data_root.bat"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\assert_install_stopped.ps1" -InstallRoot "%CD%" -DataRoot "%CAMPUSFACE_DATA_ROOT%"
if errorlevel 1 exit /b 21
set "RUNTIME_ROOT=%CAMPUSFACE_DATA_ROOT%\runtime"
set "DOWNLOAD_ROOT=%CAMPUSFACE_DATA_ROOT%\downloads"
set "LOG_ROOT=%CAMPUSFACE_DATA_ROOT%\logs"
if not exist "%CAMPUSFACE_DATA_ROOT%" mkdir "%CAMPUSFACE_DATA_ROOT%" >nul 2>nul
if not exist "%RUNTIME_ROOT%" mkdir "%RUNTIME_ROOT%" >nul 2>nul
if not exist "%DOWNLOAD_ROOT%" mkdir "%DOWNLOAD_ROOT%" >nul 2>nul
if not exist "%LOG_ROOT%" mkdir "%LOG_ROOT%" >nul 2>nul
if "%CAMPUSFACE_OFFLINE%"=="1" (
  set "PIP_NO_INDEX=1"
  set "PIP_DISABLE_PIP_VERSION_CHECK=1"
  copy /y "vendor\python-3.12.10-amd64.exe" "%DOWNLOAD_ROOT%\python-3.12.10-amd64.exe" >nul
  if errorlevel 1 exit /b 20
)

echo ============================================================
echo BAO TIN MANH HAI - SMART SETUP / UPDATE
echo Nhan dien khuon mat + camera + lich su va bang chung
echo Existing runtime/database/models are reused; no repeated long install.
echo Data: %CAMPUSFACE_DATA_ROOT%
echo ============================================================

>"%CAMPUSFACE_DATA_ROOT%\.write_test.tmp" echo CampusFace
if errorlevel 1 (
  echo [ERROR] Windows blocked writing to %CAMPUSFACE_DATA_ROOT%
  if not defined CAMPUSFACE_CHAINED pause
  exit /b 1
)
del /q "%CAMPUSFACE_DATA_ROOT%\.write_test.tmp" >nul 2>nul

set "BOOTPY="
set "BOOTPY_ARGS="
if exist "%RUNTIME_ROOT%\python\python.exe" set "BOOTPY=%RUNTIME_ROOT%\python\python.exe"
if not defined BOOTPY py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && (set "BOOTPY=py"&set "BOOTPY_ARGS=-3.12")
if not defined BOOTPY python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>nul && set "BOOTPY=python"
if not defined BOOTPY for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\find_python312.ps1"`) do if not defined BOOTPY set "BOOTPY=%%P"

if not defined BOOTPY (
  echo [0/6] Preparing private Python 3.12 runtime once...
  call :prepare_python_installer
  if errorlevel 1 exit /b 2
  call :install_private_python
  if errorlevel 1 exit /b 2
  set "BOOTPY=%RUNTIME_ROOT%\python\python.exe"
)
"%BOOTPY%" %BOOTPY_ARGS% -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
if errorlevel 1 (
  echo [ERROR] Windows x64 Python 3.12 is required. Existing runtime was not changed.
  exit /b 2
)

if not exist "%RUNTIME_ROOT%\venv\Scripts\python.exe" (
  echo [1/6] Creating CampusFace Python environment once...
  "%BOOTPY%" %BOOTPY_ARGS% -m venv "%RUNTIME_ROOT%\venv"
  if errorlevel 1 exit /b 3
)
set "PY=%RUNTIME_ROOT%\venv\Scripts\python.exe"
"%PY%" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
if errorlevel 1 exit /b 2
if "%CAMPUSFACE_OFFLINE%"=="1" (
  "%PY%" scripts\validate_portable_bundle.py
  if errorlevel 1 exit /b 20
)
"%PY%" scripts\apply_pro_r2_config.py >nul 2>nul
"%PY%" scripts\apply_camera_hd_v5_config.py >nul 2>nul

echo [2/6] Checking reusable Python runtime...
"%PY%" scripts\runtime_quick_check.py >"%LOG_ROOT%\runtime-quick-check.log" 2>&1
if errorlevel 1 (
  echo [INFO] Missing/outdated Python packages detected; installing once...
  call :install_runtime_packages
  if errorlevel 1 (
    echo [ERROR] Dependency setup failed.
    if not defined CAMPUSFACE_CHAINED pause
    exit /b 4
  )
) else (
  echo [OK] Existing Python environment reused. No pip reinstall.
)

echo [2B/6] Checking fallback Python WebRTC runtime...
"%PY%" scripts\check_v28_media_runtime.py >nul 2>nul
if errorlevel 1 (
  call :install_media_packages
  if errorlevel 1 (
    echo [ERROR] Python WebRTC runtime setup failed. Complete offline releases require all supported transports.
    if not defined CAMPUSFACE_CHAINED pause
    exit /b 4
  )
)

echo [2C/6] Installing native MediaMTX video gateway...
if "%CAMPUSFACE_OFFLINE%"=="1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\install_mediamtx_offline.ps1" -ZipPath "%CD%\vendor\mediamtx\mediamtx_v1.21.1_windows_amd64.zip" -DataRoot "%CAMPUSFACE_DATA_ROOT%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\ensure_mediamtx_v5410.ps1" -DataRoot "%CAMPUSFACE_DATA_ROOT%"
)
if errorlevel 1 (
  echo [ERROR] Native video gateway setup failed. Supply the pinned MediaMTX ZIP; offline setup never downloads it.
  if not defined CAMPUSFACE_CHAINED pause
  exit /b 4
)

echo [3/6] Preparing required FaceID and Passive PAD models...
"%PY%" scripts\prepare_core_models.py
if errorlevel 1 (
  echo [ERROR] Required FaceID/PAD model setup failed.
  if not defined CAMPUSFACE_CHAINED pause
  exit /b 5
)

echo [4/6] Checking private PostgreSQL...
if exist "%CAMPUSFACE_DATA_ROOT%\PostgreSQL\data\PG_VERSION" if exist "%CAMPUSFACE_DATA_ROOT%\config\module.env" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\ensure_postgres_running.ps1" >"%LOG_ROOT%\postgres-fast-check.log" 2>&1
  if not errorlevel 1 (
    "%PY%" scripts\check_postgres.py >nul 2>&1
    if not errorlevel 1 goto pg_ready
  )
)
call SETUP_POSTGRESQL_WINDOWS.bat
if errorlevel 1 (
  echo [ERROR] PostgreSQL setup/repair failed.
  if not defined CAMPUSFACE_CHAINED pause
  exit /b 7
)
:pg_ready
echo [OK] Existing PostgreSQL/data reused.

echo [5/6] Verifying FaceID, camera, database and frontend readiness...
"%PY%" scripts\check_ready.py
if errorlevel 1 (
  echo [ERROR] BTMH readiness check failed. Read the [ERROR] line above for the exact component.
  if not defined CAMPUSFACE_CHAINED pause
  exit /b 8
)

echo [6/6] Creating per-user shortcuts...
call CREATE_SHORTCUTS_WINDOWS.bat >nul 2>nul
echo [OK] BTMH dependencies and readiness checks completed. Real hardware acceptance remains separate.
echo [NEXT] START_CAMPUSFACE.bat
if not defined CAMPUSFACE_CHAINED pause
exit /b 0

:prepare_python_installer
set "PYINSTALLER=%DOWNLOAD_ROOT%\python-3.12.10-amd64.exe"
if "%CAMPUSFACE_OFFLINE%"=="1" if not exist "%PYINSTALLER%" exit /b 2
  if not exist "%PYINSTALLER%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try { Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%PYINSTALLER%'; exit 0 } catch { exit 1 }"
    if errorlevel 1 (
      echo [ERROR] Python runtime is not available. Use a prepared full-offline package on a fresh offline PC.
      if not defined CAMPUSFACE_CHAINED pause
      exit /b 2
    )
  )
exit /b 0

:install_private_python
  "%PYINSTALLER%" /quiet /log "%LOG_ROOT%\python_install.log" InstallAllUsers=0 TargetDir="%RUNTIME_ROOT%\python" Include_launcher=0 InstallLauncherAllUsers=0 PrependPath=0 Shortcuts=0 Include_test=0 Include_doc=0 Include_debug=0 Include_dev=0 Include_tcltk=0 Include_pip=1
  if not exist "%RUNTIME_ROOT%\python\python.exe" (
    echo [ERROR] Private Python runtime installation failed.
    if not defined CAMPUSFACE_CHAINED pause
    exit /b 2
  )
exit /b 0

:install_runtime_packages
  if "%CAMPUSFACE_OFFLINE%"=="1" (
    "%PY%" -m pip install --disable-pip-version-check --no-index --find-links="vendor\wheels" -r requirements-runtime.txt
    exit /b
  )
  if exist "vendor\wheels\*.whl" (
    "%PY%" -m pip install --no-index --find-links="vendor\wheels" -r requirements-runtime.txt
  ) else (
    "%PY%" -m pip install -r requirements-runtime.txt
  )
exit /b

:install_media_packages
  if "%CAMPUSFACE_OFFLINE%"=="1" (
    "%PY%" -m pip install --disable-pip-version-check --no-index --find-links="vendor\wheels" -r requirements-media.txt >"%LOG_ROOT%\webrtc-install.log" 2>&1
    exit /b
  )
  if exist "vendor\wheels\aiortc-*.whl" (
    "%PY%" -m pip install --no-index --find-links="vendor\wheels" -r requirements-media.txt >"%LOG_ROOT%\webrtc-install.log" 2>&1
  ) else (
    "%PY%" -m pip install -r requirements-media.txt >"%LOG_ROOT%\webrtc-install.log" 2>&1
  )
exit /b
