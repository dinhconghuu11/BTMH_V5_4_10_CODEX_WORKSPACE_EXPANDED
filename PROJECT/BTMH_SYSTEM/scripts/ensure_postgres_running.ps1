param([int]$Port = 0)
$ErrorActionPreference='Stop'

if($env:CAMPUSFACE_DATA_ROOT){
    $DataRoot=[Environment]::ExpandEnvironmentVariables($env:CAMPUSFACE_DATA_ROOT)
} else {
    $DataRoot=Join-Path $env:LOCALAPPDATA 'CampusFace'
}
$env:CAMPUSFACE_DATA_ROOT=$DataRoot
$Py=Join-Path $DataRoot 'runtime\venv\Scripts\python.exe'
$Guard=Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'postgres_guard.py'

if(-not (Test-Path $Py)){
    Write-Host '[ERROR] BTMH Face Python runtime is not installed.' -ForegroundColor Red
    Write-Host '[ACTION] Run INSTALL_NEW_PC.bat once.'
    exit 20
}
if(-not (Test-Path $Guard)){
    Write-Host '[ERROR] PostgreSQL supervisor script is missing.' -ForegroundColor Red
    exit 21
}

Write-Host '[PG] V3.3 bounded PostgreSQL supervisor starting...'
& $Py -u $Guard ensure
exit $LASTEXITCODE
