@echo off
setlocal EnableExtensions
set "BTMH_ENV=development"
call "%~dp0START_CAMPUSFACE.bat" --development
exit /b %ERRORLEVEL%
