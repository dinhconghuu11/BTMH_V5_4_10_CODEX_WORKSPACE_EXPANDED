@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo CampusFace V1.12.0 PostgreSQL Offline - START HERE
echo Static Camera Recognition Module
echo ============================================================
echo.
echo This is the recommended entry point.
echo - If CampusFace is installed, it starts immediately.
echo - If a prepared offline bundle is present, it installs offline.
echo - Otherwise an existing local Python 3.12 can perform one-time setup.
echo.
call SETUP_AND_START_CAMPUSFACE_WINDOWS.bat
exit /b %ERRORLEVEL%
