@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo BTMH V5.4.10 - BUILD FULL OFFLINE PACKAGE
echo ============================================================
echo Run this only on ONE Windows build PC with Internet.
echo It prepares Python, PostgreSQL, wheels and AI models, then creates the ZIP.
echo.
call PREPARE_PORTABLE_OFFLINE_WINDOWS.bat
if errorlevel 1 exit /b %ERRORLEVEL%
call BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat
exit /b %ERRORLEVEL%
