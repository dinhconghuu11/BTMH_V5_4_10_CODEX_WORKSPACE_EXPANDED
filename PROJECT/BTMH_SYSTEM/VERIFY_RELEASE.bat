@echo off
setlocal
cd /d "%~dp0"
python VERIFY_RELEASE.py
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
