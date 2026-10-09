@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo CampusFace V1.11.0 Passive Classroom - OPTIONAL YOLO26 FarFace TRAINING ENVIRONMENT
echo This is isolated from the stable CampusFace runtime.
echo ============================================================
set "PY="
where py >nul 2>nul && set "PY=py -3.12"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python 3.12 not found on this training PC.
  pause
  exit /b 2
)
if not exist ".venv-training\Scripts\python.exe" %PY% -m venv .venv-training
if errorlevel 1 exit /b 3
.venv-training\Scripts\python.exe -m pip install --upgrade pip
.venv-training\Scripts\python.exe -m pip install -r training\requirements-training.txt
if errorlevel 1 (
  echo [ERROR] Could not install YOLO training packages.
  pause
  exit /b 4
)
echo [OK] Training environment ready.
echo [NEXT] Add dataset, then run AUDIT_YOLO_FARFACE_DATASET_WINDOWS.bat and TRAIN_YOLO_FARFACE_WINDOWS.bat
pause
