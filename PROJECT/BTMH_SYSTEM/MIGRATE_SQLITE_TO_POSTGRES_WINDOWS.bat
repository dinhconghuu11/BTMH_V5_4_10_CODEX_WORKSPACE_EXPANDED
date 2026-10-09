@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "OLD_DB=%LOCALAPPDATA%\CampusFaceV1\data\recognition_module.db"
set "OLD_KEY=%LOCALAPPDATA%\CampusFaceV1\data\face_templates.key"
if not "%~1"=="" set "OLD_DB=%~1"
if not exist "%OLD_DB%" (
  echo [ERROR] Old SQLite database not found: %OLD_DB%
  echo Usage: MIGRATE_SQLITE_TO_POSTGRES_WINDOWS.bat "C:\path\recognition_module.db"
  exit /b 2
)
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run INSTALL_CURRENT_PC_WINDOWS.bat first.
  exit /b 3
)
echo [MIGRATE] Source: %OLD_DB%
.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --sqlite "%OLD_DB%" --old-key "%OLD_KEY%"
if errorlevel 1 exit /b 4
echo [OK] Migration finished. The old SQLite file was kept unchanged.
pause
