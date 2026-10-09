param()
$ErrorActionPreference='Stop'

function Is-Admin {
    $id=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=New-Object Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if(-not (Is-Admin)){
    Write-Host '[ERROR] Administrator rights are required for the PostgreSQL compatibility override.' -ForegroundColor Red
    exit 5
}

if($env:CAMPUSFACE_DATA_ROOT){
    $DataRoot=[Environment]::ExpandEnvironmentVariables($env:CAMPUSFACE_DATA_ROOT)
}else{
    $DataRoot=Join-Path $env:LOCALAPPDATA 'CampusFace'
}
$EnvFile=Join-Path $DataRoot 'config\module.env'
$PgBin=Join-Path $DataRoot 'runtime\PostgreSQL17\bin'
if(Test-Path $EnvFile){
    foreach($line in (Get-Content -LiteralPath $EnvFile -ErrorAction SilentlyContinue)){
        if($line -match '^\s*CAMPUSFACE_POSTGRES_BIN\s*=\s*(.+?)\s*$'){
            $candidate=[Environment]::ExpandEnvironmentVariables($Matches[1].Trim().Trim('"').Trim("'"))
            if($candidate){ $PgBin=$candidate }
        }
    }
}
$Postgres=Join-Path $PgBin 'postgres.exe'
$PgCtl=Join-Path $PgBin 'pg_ctl.exe'
if(-not (Test-Path $Postgres)){
    Write-Host "[ERROR] postgres.exe not found: $Postgres" -ForegroundColor Red
    exit 6
}

try{
    Import-Module ProcessMitigations -ErrorAction Stop
}catch{
    Write-Host '[ERROR] Windows ProcessMitigations module is unavailable.' -ForegroundColor Red
    exit 7
}

Write-Host '============================================================'
Write-Host 'BTMH PostgreSQL Windows 487 compatibility repair'
Write-Host 'Scope: private BTMH PostgreSQL executables only'
Write-Host '============================================================'
Write-Host "[PG] $Postgres"

# PostgreSQL on Windows can fail to create child processes with Win32 error 487
# when Bottom-up ASLR prevents reservation at the postmaster shared-memory
# address. Disable only that mitigation for the private PostgreSQL binaries.
Set-ProcessMitigation -Name $Postgres -Disable BottomUp
if(Test-Path $PgCtl){ Set-ProcessMitigation -Name $PgCtl -Disable BottomUp }

$Marker=Join-Path $DataRoot 'config\postgres_windows_487_mitigation.applied'
New-Item -ItemType Directory -Force (Split-Path $Marker -Parent) | Out-Null
"Applied=$(Get-Date -Format o)`r`nPostgres=$Postgres`r`nMitigation=BottomUp ASLR disabled for this executable only" | Set-Content -LiteralPath $Marker -Encoding UTF8
Write-Host '[OK] PostgreSQL-only Bottom-up ASLR compatibility override applied.' -ForegroundColor Green
Write-Host '[NOTE] DEP/CFG and other Windows exploit protections were not changed.'
exit 0
