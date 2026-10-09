@echo off
setlocal
chcp 65001 >nul
set "BTMH_ENV=production"
set "BTMH_NETWORK_MODE=lan"
set "BTMH_ALLOW_LAN=1"
set "MODULE_HOST=0.0.0.0"
echo ===============================================================
echo  BAO TIN MANH HAI - LAN MODE
echo  Chi su dung trong mang noi bo duoc tin cay.
echo  Khong NAT/mo cong 8100 truc tiep ra Internet.
echo ===============================================================
call "%~dp0START_CAMPUSFACE.bat"
endlocal
