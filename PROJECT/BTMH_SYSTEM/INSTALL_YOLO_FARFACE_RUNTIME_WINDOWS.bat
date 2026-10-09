@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo CampusFace V1.11.0 Passive Classroom - OPTIONAL YOLO FarFace runtime
Echo Stable V1 works without this step using YuNet + SFace.
echo ============================================================
set "PY="
if exist "runtime\venv\Scripts\python.exe" set "PY=runtime\venv\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  echo [ERROR] Main CampusFace runtime is not installed.
  pause
  exit /b 2
)
%PY% -m pip install "ultralytics>=8.3"
if errorlevel 1 (
  echo [ERROR] Ultralytics runtime installation failed. Stable YuNet mode is unchanged.
  pause
  exit /b 3
)
if not exist "models\campusface-face-yolo.pt" (
  echo [WARN] Runtime installed, but models\campusface-face-yolo.pt is not present yet.
)
echo [OK] Optional YOLO runtime installed. MODULE_USE_CUSTOM_FACE_YOLO=auto will activate when the model exists.
pause
