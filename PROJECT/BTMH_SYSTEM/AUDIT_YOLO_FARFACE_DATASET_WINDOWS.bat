@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY="
if exist ".venv-training\Scripts\python.exe" set "PY=.venv-training\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY where py >nul 2>nul && set "PY=py -3.12"
if not defined PY (
  echo [ERROR] Python not found. Run INSTALL_YOLO_TRAINING_WINDOWS.bat first.
  pause
  exit /b 2
)
%PY% scripts\audit_farface_dataset.py
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
