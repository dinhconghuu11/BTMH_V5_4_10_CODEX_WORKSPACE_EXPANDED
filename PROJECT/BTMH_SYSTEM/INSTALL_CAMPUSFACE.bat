@echo off
rem Compatibility alias for legacy scripts/tests. New deployment uses top-level INSTALL_NEW_PC.bat.
call "%~dp0..\..\INSTALL_NEW_PC.bat"
exit /b %ERRORLEVEL%
