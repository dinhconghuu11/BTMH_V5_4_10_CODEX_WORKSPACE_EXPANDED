@echo off
rem Legacy marker: CampusFacePostgreSQL - now private per-user PostgreSQL for BTMH Face.
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0scripts\resolve_data_root.bat"
set "PY=%CAMPUSFACE_DATA_ROOT%\runtime\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] BTMH Face Python runtime is not ready.
  echo [ACTION] Run INSTALL_NEW_PC.bat first.
  exit /b 1
)
echo ============================================================
echo BTMH Face - PRIVATE LOCAL POSTGRESQL SETUP / REPAIR
echo Local-only: 127.0.0.1 / private per-user data
echo Auto port recovery for Windows reserved/excluded ports.
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_embedded_postgres.ps1" -Root "%CD%" -Python "%PY%" -Port 55442
set "RC=%ERRORLEVEL%"
if "%RC%"=="87" (
  echo [PG-WIN-487] Exact Windows shared-memory error detected.
  call "%CD%\scripts\repair_postgres_windows_487.bat"
  if errorlevel 1 exit /b 87
  echo [PG] Retrying PostgreSQL setup after compatibility repair...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%CD%\scripts\setup_embedded_postgres.ps1" -Root "%CD%" -Python "%PY%" -Port 55442
  set "RC=%ERRORLEVEL%"
)
if not "%RC%"=="0" (
  echo [ERROR] PostgreSQL setup failed.
  echo [LOG] %CAMPUSFACE_DATA_ROOT%\logs\postgres-install.log
  exit /b %RC%
)

rem Run the self-healing guard after setup as a final bind/readiness check.
"%PY%" "%CD%\scripts\postgres_guard.py"
if errorlevel 1 (
  echo [ERROR] PostgreSQL final readiness guard failed.
  echo [LOG] %CAMPUSFACE_DATA_ROOT%\logs\postgres-runtime.log
  exit /b 8
)
if exist "%CAMPUSFACE_DATA_ROOT%\config\postgres_runtime_env.bat" call "%CAMPUSFACE_DATA_ROOT%\config\postgres_runtime_env.bat"
"%PY%" scripts\check_postgres.py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PostgreSQL process is up but application database login failed.
  exit /b 9
)
echo [OK] BTMH Face PostgreSQL is ready on 127.0.0.1:%CAMPUSFACE_POSTGRES_PORT%.
exit /b 0
