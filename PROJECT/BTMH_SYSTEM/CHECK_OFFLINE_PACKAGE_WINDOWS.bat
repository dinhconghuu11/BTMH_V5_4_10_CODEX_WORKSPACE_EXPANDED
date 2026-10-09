@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PY="
where py >nul 2>nul && set "PY=py -3.12"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY if exist "runtime\venv\Scripts\python.exe" set "PY=runtime\venv\Scripts\python.exe"
if not defined PY (
  echo [CHECK] Required offline files include:
  echo   vendor\python-3.12.10-amd64.exe
  echo   vendor\postgresql\postgresql-17.11-3-windows-x64-binaries.zip
  echo   vendor\mediamtx\mediamtx_v1.21.1_windows_amd64.zip
  echo   vendor\wheels\*.whl
  echo   models\face_detection_yunet_2023mar.onnx
  echo   models\face_recognition_sface_2021dec.onnx
  echo   models\minifasnet_v2.onnx
  echo   Acquisition hashes, checksum sidecars and complete redistribution notices
  pause
  exit /b 1
)
%PY% scripts\validate_portable_bundle.py
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
