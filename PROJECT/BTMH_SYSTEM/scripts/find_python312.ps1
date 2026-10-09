$ErrorActionPreference='SilentlyContinue'
$candidates=New-Object System.Collections.Generic.List[string]
foreach($base in @(
  'HKCU:\Software\Python\PythonCore\3.12\InstallPath',
  'HKLM:\Software\Python\PythonCore\3.12\InstallPath',
  'HKLM:\Software\WOW6432Node\Python\PythonCore\3.12\InstallPath'
)){
  if(Test-Path $base){
    try{
      $v=(Get-ItemProperty $base).'(default)'
      if(-not $v){$v=(Get-Item $base).GetValue('')}
      if($v){$candidates.Add((Join-Path $v 'python.exe'))}
    }catch{}
  }
}
$candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'))
$candidates.Add((Join-Path $env:ProgramFiles 'Python312\python.exe'))
foreach($exe in ($candidates|Select-Object -Unique)){
  if(Test-Path $exe){
    try{
      & $exe -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) else 1)" 2>$null
      if($LASTEXITCODE -eq 0){ Write-Output $exe; exit 0 }
    }catch{}
  }
}
exit 1
