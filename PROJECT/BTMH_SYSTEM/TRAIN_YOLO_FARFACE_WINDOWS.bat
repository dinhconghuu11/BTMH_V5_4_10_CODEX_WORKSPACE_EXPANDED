@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv-training\Scripts\python.exe" (
  echo [ERROR] Training environment not found.
  echo [ACTION] Run INSTALL_YOLO_TRAINING_WINDOWS.bat first.
  pause
  exit /b 2
)
.venv-training\Scripts\python.exe scripts\audit_farface_dataset.py
if errorlevel 1 (
  echo [STOP] Dataset audit failed.
  pause
  exit /b 3
)
if not exist "training\base_models\yolo26n.pt" (
  echo [ERROR] Missing training\base_models\yolo26n.pt
  echo Put the YOLO26 pretrained model there before training.
  pause
  exit /b 4
)
echo [TRAIN] YOLO26 FarFace / imgsz 1280 / 160 epochs
.venv-training\Scripts\python.exe scripts\train_farface_yolo.py --model training\base_models\yolo26n.pt --imgsz 1280 --epochs 160
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
