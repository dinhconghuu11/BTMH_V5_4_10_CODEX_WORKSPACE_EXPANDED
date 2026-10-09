@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY="
if exist "runtime\venv\Scripts\python.exe" set "PY=runtime\venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py -3.12"
)
if not defined PY (
  echo [ERROR] CampusFace runtime not found.
  echo [ACTION] Run INSTALL_CAMPUSFACE_V1_WINDOWS.bat or INSTALL_CURRENT_PC_WINDOWS.bat.
  pause
  exit /b 2
)
%PY% scripts\check_ready.py
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
