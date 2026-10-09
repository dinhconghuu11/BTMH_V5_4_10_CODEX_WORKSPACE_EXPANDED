@echo off
rem CampusFace stable data-root resolver.
rem Existing V1.14.x customers keep their current data automatically.
rem Fresh customer installs use the version-independent CampusFace folder.
if defined CAMPUSFACE_DATA_ROOT exit /b 0
set "CF_STABLE_ROOT=%LOCALAPPDATA%\CampusFace"
set "CF_LEGACY_ROOT=%LOCALAPPDATA%\CampusFaceV1142"
if exist "%CF_STABLE_ROOT%\config\module.env" (
  set "CAMPUSFACE_DATA_ROOT=%CF_STABLE_ROOT%"
  exit /b 0
)
if exist "%CF_STABLE_ROOT%\PostgreSQL\data\PG_VERSION" (
  set "CAMPUSFACE_DATA_ROOT=%CF_STABLE_ROOT%"
  exit /b 0
)
if exist "%CF_LEGACY_ROOT%\config\module.env" (
  set "CAMPUSFACE_DATA_ROOT=%CF_LEGACY_ROOT%"
  exit /b 0
)
if exist "%CF_LEGACY_ROOT%\PostgreSQL\data\PG_VERSION" (
  set "CAMPUSFACE_DATA_ROOT=%CF_LEGACY_ROOT%"
  exit /b 0
)
set "CAMPUSFACE_DATA_ROOT=%CF_STABLE_ROOT%"
exit /b 0
