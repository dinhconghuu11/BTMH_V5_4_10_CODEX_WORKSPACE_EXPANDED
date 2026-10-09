@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
call "%~dp0resolve_data_root.bat"
echo ============================================================
echo BTMH - REPAIR POSTGRESQL WINDOWS ERROR 487
echo This is only used after the exact shared-memory error is detected.
echo Windows will ask for Administrator approval once.
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0repair_postgres_windows_487.ps1'); exit $p.ExitCode"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [ERROR] Windows 487 compatibility repair was not applied. Code %RC%.
  exit /b %RC%
)
echo [OK] Compatibility repair applied. PostgreSQL can be retried now.
exit /b 0
