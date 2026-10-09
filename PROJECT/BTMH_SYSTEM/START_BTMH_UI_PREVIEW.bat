@echo off
setlocal
cd /d "%~dp0"
title BTMH UI PREVIEW - localhost only
set "PREVIEW_PY=%BTMH_UI_PREVIEW_PYTHON%"
if defined PREVIEW_PY goto check_python
set "PREVIEW_PY=%LOCALAPPDATA%\CampusFace\runtime\venv\Scripts\python.exe"
if exist "%PREVIEW_PY%" goto check_python
set "PREVIEW_PY=%LOCALAPPDATA%\CampusFaceV1142\runtime\venv\Scripts\python.exe"
if exist "%PREVIEW_PY%" goto check_python
set "PREVIEW_PY=%~dp0..\..\.test_venv\Scripts\python.exe"
:check_python
if not exist "%PREVIEW_PY%" (
  echo [BLOCKED] Existing BTMH Python runtime not found.
  echo Set BTMH_UI_PREVIEW_PYTHON to an existing python.exe with BTMH dependencies.
  echo No download or installation will be attempted.
  pause
  exit /b 2
)
echo [MODE] UI PREVIEW - separate SQLite data, localhost only
echo [URL] http://127.0.0.1:8810/
echo Open this URL in Chrome or Edge after the server is ready.
"%PREVIEW_PY%" -B "%~dp0run_ui_preview.py"
set "PREVIEW_EXIT=%ERRORLEVEL%"
if not "%PREVIEW_EXIT%"=="0" pause
exit /b %PREVIEW_EXIT%
