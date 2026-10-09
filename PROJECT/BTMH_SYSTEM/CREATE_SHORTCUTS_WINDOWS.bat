@echo off
setlocal EnableExtensions
cd /d "%~dp0"
for %%I in ("%~dp0..\..") do set "CAMPUSFACE_ROOT=%%~fI"
set "STARTER=%CAMPUSFACE_ROOT%\START_CAMPUSFACE.bat"
if not exist "%STARTER%" set "STARTER=%CD%\START_CAMPUSFACE.bat"

echo Creating Bao Tin Manh Hai shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $p='%STARTER%'; $root='%CAMPUSFACE_ROOT%'; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Bao Tin Manh Hai.lnk'); $s.TargetPath=$env:ComSpec; $s.Arguments='/c ""'+$p+'""'; $s.WorkingDirectory=$root; $s.Save(); $m=$ws.CreateShortcut([Environment]::GetFolderPath('StartMenu')+'\Programs\Bao Tin Manh Hai.lnk'); $m.TargetPath=$env:ComSpec; $m.Arguments='/c ""'+$p+'""'; $m.WorkingDirectory=$root; $m.Save()"
if errorlevel 1 (
  echo [WARN] Could not create one or more shortcuts.
  exit /b 1
)
echo [OK] Desktop and Start Menu shortcuts created.
exit /b 0
