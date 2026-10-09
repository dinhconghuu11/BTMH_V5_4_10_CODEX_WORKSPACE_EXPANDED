#define MyAppName "BTMH"
#define MyAppVersion "5.4.10"
#define MyAppPublisher "Bao Tin Manh Hai"
#ifndef BundleRoot
  #error Build with BUILD_SETUP_EXE_WINDOWS.bat after payload verification.
#endif
#ifndef BuildStamp
  #error BuildStamp is required.
#endif

[Setup]
AppId={{B3AB8878-6D9B-4B22-A2B8-A8B010120001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\BTMH
DefaultGroupName=BTMH
OutputDir=output
OutputBaseFilename=BTMH_Setup_V5.4.10_{#BuildStamp}
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
MinVersion=10.0.14393
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\frontend\favicon.ico
UninstallFilesDir={localappdata}\BTMH\uninstall

[Files]
Source: "{#BundleRoot}\scripts\assert_install_stopped.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#BundleRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{localappdata}\CampusFace\data"
Name: "{localappdata}\CampusFace\logs"
Name: "{localappdata}\CampusFace\backups"
Name: "{localappdata}\CampusFace\config"

[Icons]
Name: "{autoprograms}\BTMH"; Filename: "{cmd}"; Parameters: "/c ""{app}\START_CAMPUSFACE.bat"""; WorkingDir: "{app}"
Name: "{autodesktop}\BTMH"; Filename: "{cmd}"; Parameters: "/c ""{app}\START_CAMPUSFACE.bat"""; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng BTMH trên Desktop"; GroupDescription: "Tùy chọn:"

[Run]
Filename: "{cmd}"; Parameters: "/c ""{app}\START_CAMPUSFACE.bat"""; WorkingDir: "{app}"; Description: "Khởi động BTMH"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c ""{app}\STOP_POSTGRESQL_WINDOWS.bat"" uninstall"; WorkingDir: "{app}"; Flags: runhidden waituntilterminated skipifdoesntexist

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then begin
    ExtractTemporaryFile('assert_install_stopped.ps1');
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\assert_install_stopped.ps1') + '" -InstallRoot "' + ExpandConstant('{app}') + '"', ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('BTMH upgrade process check could not start.');
    if ResultCode <> 0 then
      RaiseException('Stop BTMH and its private PostgreSQL process before installing or upgrading. Existing data was not reset.');
  end;
  if CurStep = ssPostInstall then begin
    if not Exec(ExpandConstant('{cmd}'), '/c ""' + ExpandConstant('{app}\SETUP_OFFLINE_WINDOWS.bat') + '""', ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      RaiseException('BTMH offline dependency setup could not start.');
    if ResultCode <> 0 then
      RaiseException('BTMH offline setup failed. Check the component error and logs; installation is not ready.');
  end;
end;
