@echo off
setlocal EnableExtensions
call "%~dp0scripts\resolve_data_root.bat"
set "PGBIN=%CAMPUSFACE_DATA_ROOT%\runtime\PostgreSQL17\bin"
set "PGDATA=%CAMPUSFACE_DATA_ROOT%\PostgreSQL\data"
if exist "%PGBIN%\pg_ctl.exe" if exist "%PGDATA%\PG_VERSION" "%PGBIN%\pg_ctl.exe" stop -D "%PGDATA%" -m fast -w -t 30
exit /b 0
