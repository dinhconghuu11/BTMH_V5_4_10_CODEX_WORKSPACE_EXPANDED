@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================================
echo  BTMH SECURITY V5.4 - TAO CHU SO HUU LAN DAU
echo  Chi chay truc tiep tren PC trung tam.
echo ===============================================================
python CREATE_OWNER_FIRST_RUN.py
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
