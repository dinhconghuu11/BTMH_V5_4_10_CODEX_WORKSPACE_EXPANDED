@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo BTMH V5.4.10 - FULL OFFLINE CUSTOMER INSTALLER
echo Python + wheels + AI models + private PostgreSQL
 echo ============================================================
rem PostgreSQL and the private runtime belong to the current standard user.
set "CAMPUSFACE_OFFLINE=1"
set "CAMPUSFACE_CHAINED=1"
call INSTALL_CURRENT_PC_WINDOWS.bat
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%
echo [OK] BTMH offline installation/repair completed. Start the production launcher for readiness and Owner setup.
if not defined CAMPUSFACE_CHAINED pause
exit /b 0

