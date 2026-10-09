param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Python,
    [int]$Port = 55442
)

$ErrorActionPreference = 'Stop'
$script:ExitCode = 1
$ProgressPreference = 'SilentlyContinue'

if($env:CAMPUSFACE_DATA_ROOT){
    $DataRoot = [Environment]::ExpandEnvironmentVariables($env:CAMPUSFACE_DATA_ROOT)
} else {
    $DataRoot = Join-Path $env:LOCALAPPDATA 'CampusFace'
}
$env:CAMPUSFACE_DATA_ROOT = $DataRoot

$PgPrefix = Join-Path $DataRoot 'runtime\PostgreSQL17'
$PgData = Join-Path $DataRoot 'PostgreSQL\data'
$PgLogRoot = Join-Path $DataRoot 'logs'
$ConfigRoot = Join-Path $DataRoot 'config'
$SecretPath = Join-Path $DataRoot 'data\postgres_app_password.dpapi'
$ModuleEnv = Join-Path $ConfigRoot 'module.env'
$VendorDir = Join-Path $Root 'vendor\postgresql'
$BundledArchive = Join-Path $VendorDir 'postgresql-17.11-3-windows-x64-binaries.zip'
$BundledHash = "$BundledArchive.sha256"
$DownloadDir = Join-Path $DataRoot 'downloads'
$DownloadedArchive = Join-Path $DownloadDir 'postgresql-17.11-3-windows-x64-binaries.zip'
$DownloadUrl = 'https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip'
$Transcript = Join-Path $PgLogRoot 'postgres-install.log'

New-Item -ItemType Directory -Force -Path $DataRoot,$PgLogRoot,(Join-Path $DataRoot 'data'),$ConfigRoot,(Join-Path $DataRoot 'backups'),$DownloadDir | Out-Null
try { Start-Transcript -Path $Transcript -Append -Force | Out-Null } catch {}

function Say([string]$m) { Write-Host $m }
function Fail([string]$code,[string]$m) {
    Write-Host "[ERROR][$code] $m" -ForegroundColor Red
    Write-Host "[LOG] $Transcript"
    throw "$code $m"
}
function Test-DirectoryIo([string]$Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $a=Join-Path $Path ('.cf-write-'+[guid]::NewGuid().ToString('N')+'.tmp')
    $b="$a.renamed"
    try {
        [IO.File]::WriteAllText($a,'CampusFace IO test',[Text.Encoding]::UTF8)
        if((Get-Content -LiteralPath $a -Raw) -notmatch 'CampusFace IO test'){ throw 'read verification failed' }
        Move-Item -LiteralPath $a -Destination $b -Force
        Remove-Item -LiteralPath $b -Force
    } catch {
        Fail 'FS-IO-001' "CampusFace cannot safely write to $Path : $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $a -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $b -Force -ErrorAction SilentlyContinue
    }
}
function Test-Port([int]$p) {
    $c=New-Object System.Net.Sockets.TcpClient
    try {
        $a=$c.BeginConnect('127.0.0.1',$p,$null,$null)
        if(-not $a.AsyncWaitHandle.WaitOne(600)){ return $false }
        $c.EndConnect($a); return $true
    } catch { return $false } finally { $c.Dispose() }
}
function Wait-Port([int]$p,[int]$seconds=45) {
    $until=(Get-Date).AddSeconds($seconds)
    do { if(Test-Port $p){ return $true }; Start-Sleep -Milliseconds 500 } while((Get-Date)-lt$until)
    return $false
}
function Wait-PortClosed([int]$p,[int]$seconds=25) {
    $until=(Get-Date).AddSeconds($seconds)
    do { if(-not (Test-Port $p)){ return $true }; Start-Sleep -Milliseconds 500 } while((Get-Date)-lt$until)
    return $false
}
function New-Password([int]$length=48) {
    $chars='abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%_-'
    $bytes=New-Object byte[] $length
    $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $sb=New-Object System.Text.StringBuilder
    foreach($b in $bytes){ [void]$sb.Append($chars[$b % $chars.Length]) }
    return 'Cf9A!' + $sb.ToString()
}
function Get-PgMajor([string]$bin) {
    $exe=Join-Path $bin 'postgres.exe'
    if(-not (Test-Path $exe)){ return 0 }
    try {
        $v=& $exe --version 2>$null
        if($v -match 'PostgreSQL(?:\)|\s)+\s*(\d+)'){ return [int]$Matches[1] }
    } catch {}
    return 0
}
function Find-SystemPg17Root {
    $candidates=New-Object System.Collections.Generic.List[string]
    $common=Join-Path $env:ProgramFiles 'PostgreSQL\17'
    if(Test-Path (Join-Path $common 'bin\postgres.exe')){ $candidates.Add($common) }
    foreach($regBase in @('HKLM:\SOFTWARE\PostgreSQL\Installations','HKLM:\SOFTWARE\WOW6432Node\PostgreSQL\Installations')){
        if(Test-Path $regBase){
            Get-ChildItem $regBase -ErrorAction SilentlyContinue | ForEach-Object {
                try {
                    $p=Get-ItemProperty $_.PSPath
                    foreach($prop in @('Base Directory','BaseDirectory','Install Path','InstallPath')){
                        $val=$p.$prop
                        if($val -and (Test-Path (Join-Path $val 'bin\postgres.exe'))){ $candidates.Add([string]$val) }
                    }
                } catch {}
            }
        }
    }
    foreach($root in ($candidates | Select-Object -Unique)){
        if((Get-PgMajor (Join-Path $root 'bin')) -eq 17){ return $root }
    }
    return $null
}
function Copy-Runtime([string]$sourceRoot) {
    Say "[PG] Preparing private PostgreSQL runtime from: $sourceRoot"
    New-Item -ItemType Directory -Force -Path $PgPrefix | Out-Null
    foreach($name in @('bin','lib','share')){
        $s=Join-Path $sourceRoot $name
        if(-not (Test-Path $s)){ Fail 'PG-RUNTIME-003' "PostgreSQL runtime is missing $name in $sourceRoot" }
        $d=Join-Path $PgPrefix $name
        if(Test-Path $d){ Remove-Item -Recurse -Force $d }
        Copy-Item -Recurse -Force $s $d
    }
}
function Expand-RuntimeArchive([string]$Archive,[string]$HashFile='') {
    if($env:CAMPUSFACE_OFFLINE -eq '1' -and (-not $HashFile -or -not (Test-Path -LiteralPath $HashFile))){
        Fail 'PG-OFFLINE-002' 'The PostgreSQL acquisition checksum is missing. Rebuild the verified offline bundle.'
    }
    if($HashFile -and (Test-Path $HashFile)){
        $expected=((Get-Content $HashFile -Raw).Trim().Split(' ')[0]).ToUpperInvariant()
        $actual=(Get-FileHash -Algorithm SHA256 $Archive).Hash.ToUpperInvariant()
        if($expected -and $expected -ne $actual){ Fail 'PG-RUNTIME-004' 'PostgreSQL archive checksum mismatch.' }
    }
    $tmp=Join-Path $env:TEMP ('CampusFace-PG-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    try {
        Say '[PG] Expanding PostgreSQL runtime...'
        Expand-Archive -LiteralPath $Archive -DestinationPath $tmp -Force
        $postgres=Get-ChildItem $tmp -Recurse -Filter postgres.exe -File -ErrorAction SilentlyContinue | Where-Object { $_.Directory.Name -ieq 'bin' } | Select-Object -First 1
        if(-not $postgres){ Fail 'PG-RUNTIME-005' 'postgres.exe was not found inside the PostgreSQL runtime archive.' }
        Copy-Runtime $postgres.Directory.Parent.FullName
    } finally { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
}
function Ensure-PrivateRuntime {
    if((Get-PgMajor (Join-Path $PgPrefix 'bin')) -eq 17){ Say '[OK] Private PostgreSQL 17 runtime is present.'; return }
    if(Test-Path $BundledArchive){ Expand-RuntimeArchive $BundledArchive $BundledHash }
    else {
        if($env:CAMPUSFACE_OFFLINE -eq '1'){
            Fail 'PG-OFFLINE-001' 'The verified bundled PostgreSQL archive is missing. Offline setup never downloads or substitutes a system runtime.'
        }
        $system=Find-SystemPg17Root
        if($system){
            Say '[PG] Existing PostgreSQL 17 detected. CampusFace copies only runtime binaries and never modifies its service or data.'
            Copy-Runtime $system
        } else {
            Say '[PG] Downloading official PostgreSQL 17 binary runtime once...'
            try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 120 -Uri $DownloadUrl -OutFile $DownloadedArchive }
            catch { Fail 'PG-RUNTIME-001' 'Cannot obtain PostgreSQL runtime. Use a full offline package for customer delivery.' }
            Expand-RuntimeArchive $DownloadedArchive
        }
    }
    if((Get-PgMajor (Join-Path $PgPrefix 'bin')) -ne 17){ Fail 'PG-RUNTIME-002' 'Private PostgreSQL runtime validation failed.' }
    Say '[OK] Dedicated user-managed PostgreSQL runtime is ready.'
}
function Get-ServerOptions { return "-h 127.0.0.1 -p $Port" }
function Refresh-PortFromConfig {
    if(Test-Path $ModuleEnv){
        try {
            foreach($line in (Get-Content $ModuleEnv -ErrorAction SilentlyContinue)){
                if($line -match '^\s*CAMPUSFACE_POSTGRES_PORT\s*=\s*(\d+)\s*$'){
                    $saved=[int]$Matches[1]
                    if($saved -ge 1024 -and $saved -le 65535){ $script:Port=$saved; return }
                }
            }
        } catch {}
    }
}
function Test-PortBindable([int]$p) {
    $listener=$null
    try {
        $ip=[System.Net.IPAddress]::Parse('127.0.0.1')
        $listener=New-Object System.Net.Sockets.TcpListener($ip,$p)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if($listener){ try { $listener.Stop() } catch {} }
    }
}
function Find-FreePort([int]$preferred) {
    # Kept only for compatibility with old support scripts. The V3.3 Python
    # supervisor is authoritative and performs the final bind/excluded-port test.
    if(-not (Test-Port $preferred) -and (Test-PortBindable $preferred)){ return $preferred }
    $candidates=@()
    for($p=$preferred+1;$p -le [Math]::Min($preferred+160,65535);$p++){ $candidates += $p }
    for($p=54320;$p -le 54519;$p++){ $candidates += $p }
    foreach($p in ($candidates | Select-Object -Unique)){
        if(-not (Test-Port $p) -and (Test-PortBindable $p)){ return $p }
    }
    return $preferred
}
function Start-PrivatePostgres([string]$logName='postgres-runtime.log') {
    Say '[PG] Starting via V3.3 bounded supervisor (no infinite wait)...'
    & $Python -u (Join-Path $Root 'scripts\postgres_guard.py') ensure
    $guardRc=$LASTEXITCODE
    if($guardRc -ne 0){
        if($guardRc -eq 87){ $script:ExitCode = 87 }
        $log=Join-Path $PgLogRoot $logName
        if(Test-Path $log){ Write-Host '[PG LOG]'; Get-Content $log -Tail 120 -ErrorAction SilentlyContinue }
        Fail 'PG-START-001' 'Private PostgreSQL process could not start.'
    }
    Refresh-PortFromConfig
}
function Stop-PrivatePostgres {
    & $Python -u (Join-Path $Root 'scripts\postgres_guard.py') stop
    if($LASTEXITCODE -ne 0){
        Fail 'PG-STOP-001' 'Private PostgreSQL process could not stop inside the hard timeout.'
    }
}
function Ensure-Cluster {
    $script:NewCluster=$false
    $script:SuperPassword=$null
    $version=Join-Path $PgData 'PG_VERSION'
    if(Test-Path $version){ return }
    if(Test-Path $PgData){
        $items=Get-ChildItem $PgData -Force -ErrorAction SilentlyContinue
        if($items){
            $backup=Join-Path $DataRoot ('recovery\postgres-incomplete-'+(Get-Date -Format yyyyMMdd-HHmmss))
            New-Item -ItemType Directory -Force (Split-Path $backup -Parent) | Out-Null
            Say "[RECOVERY] Moving incomplete PostgreSQL data to $backup"
            Move-Item $PgData $backup
        }
    }
    New-Item -ItemType Directory -Force $PgData | Out-Null
    Test-DirectoryIo (Split-Path $PgData -Parent)
    $script:SuperPassword=New-Password 44
    $pw=Join-Path $env:TEMP ('cf-pg-pw-'+[guid]::NewGuid().ToString('N')+'.txt')
    [IO.File]::WriteAllText($pw,$script:SuperPassword,[Text.Encoding]::ASCII)
    try {
        Say '[PG] Initializing private PostgreSQL cluster for the current Windows user...'
        & (Join-Path $PgPrefix 'bin\initdb.exe') -D $PgData -U postgres -A scram-sha-256 --pwfile=$pw -E UTF8
        if($LASTEXITCODE -ne 0){ Fail 'PG-INIT-001' 'initdb failed.' }
    } finally { Remove-Item -Force $pw -ErrorAction SilentlyContinue }
    $script:NewCluster=$true
    Say '[OK] Private PostgreSQL cluster initialized.'
}
function Save-Config {
    New-Item -ItemType Directory -Force $ConfigRoot | Out-Null
    Test-DirectoryIo $ConfigRoot
    $desired=[ordered]@{
        'CAMPUSFACE_DATA_ROOT'=$DataRoot
        'CAMPUSFACE_DB_MODE'='postgres'
        'CAMPUSFACE_POSTGRES_HOST'='127.0.0.1'
        'CAMPUSFACE_POSTGRES_PORT'="$Port"
        'CAMPUSFACE_POSTGRES_DB'='campusface'
        'CAMPUSFACE_POSTGRES_USER'='campusface_app'
        'CAMPUSFACE_POSTGRES_SSLMODE'='disable'
        'CAMPUSFACE_POSTGRES_BIN'=(Join-Path $PgPrefix 'bin')
        'CAMPUSFACE_POSTGRES_LAUNCH_MODE'='user-process'
        'CAMPUSFACE_POSTGRES_DATA'=$PgData
    }
    $lines=@()
    if(Test-Path $ModuleEnv){ try { $lines=Get-Content -LiteralPath $ModuleEnv -ErrorAction Stop } catch { $lines=@() } }
    elseif(Test-Path (Join-Path $Root 'module.env.example')){ $lines=Get-Content -LiteralPath (Join-Path $Root 'module.env.example') }
    $out=New-Object System.Collections.Generic.List[string]
    $seen=@{}
    foreach($line in $lines){
        if($line -match '^\s*([^#=]+)=(.*)$'){
            $key=$Matches[1].Trim()
            if($desired.Contains($key)){ $out.Add("$key=$($desired[$key])"); $seen[$key]=$true; continue }
        }
        $out.Add($line)
    }
    foreach($k in $desired.Keys){ if(-not $seen.ContainsKey($k)){ $out.Add("$k=$($desired[$k])") } }
    $tmp="$ModuleEnv.tmp"
    [IO.File]::WriteAllLines($tmp,$out,[Text.Encoding]::UTF8)
    Move-Item -LiteralPath $tmp -Destination $ModuleEnv -Force
    Say "[OK] Local configuration saved to $ModuleEnv"
}
function Invoke-Python([string[]]$PyArgs) {
    & $Python @PyArgs
    return ($LASTEXITCODE -eq 0)
}
function Restart-PrivatePostgres {
    Stop-PrivatePostgres
    Start-PrivatePostgres 'postgres-runtime.log'
}
function Bootstrap-Database {
    if(Test-Path $SecretPath){
        if(Invoke-Python -PyArgs @('scripts\check_postgres.py')){ Say '[OK] Existing CampusFace database credential is valid. Customer data preserved.'; return }
        Fail 'PG-DATA-001' 'A CampusFace database credential exists but validation failed. Existing customer data was NOT reset.'
    }
    $appPw=New-Password 52
    if($script:NewCluster){
        Say '[PG] Creating campusface database and restricted application account...'
        & $Python 'scripts\bootstrap_postgres.py' '--super-password' $script:SuperPassword '--app-password' $appPw '--port' "$Port"
        if($LASTEXITCODE -ne 0){ Fail 'PG-BOOTSTRAP-001' 'New PostgreSQL database bootstrap failed.' }
    } else {
        Say '[RECOVERY] Existing user cluster has no CampusFace credential. Enabling temporary localhost-only recovery...'
        & $Python 'scripts\pg_hba_recovery.py' 'enable' '--data-dir' $PgData
        if($LASTEXITCODE -ne 0){ Fail 'PG-RECOVERY-001' 'Could not enable credential recovery.' }
        try {
            Restart-PrivatePostgres
            $newSuper=New-Password 44
            & $Python 'scripts\bootstrap_postgres.py' '--super-password' $newSuper '--app-password' $appPw '--port' "$Port" '--reset-super-password'
            if($LASTEXITCODE -ne 0){ Fail 'PG-RECOVERY-003' 'Credential recovery bootstrap failed.' }
        } finally {
            & $Python 'scripts\pg_hba_recovery.py' 'restore' '--data-dir' $PgData | Out-Null
            Restart-PrivatePostgres
        }
    }
    if(-not (Invoke-Python -PyArgs @('scripts\check_postgres.py'))){ Fail 'PG-CHECK-001' 'Final PostgreSQL validation failed.' }
    Say '[OK] CampusFace PostgreSQL database bootstrap completed.'
}

try {
    Say '============================================================'
    Say 'CampusFace V1 FACE - USER-MANAGED POSTGRESQL SETUP'
    Say 'No Windows service. No Scheduled Task. No shared-machine ACL repair.'
    Say 'All mutable data belongs to the current Windows user.'
    Say '============================================================'

    foreach($dir in @($DataRoot,(Join-Path $DataRoot 'data'),$ConfigRoot,$PgLogRoot,(Join-Path $DataRoot 'backups'),(Join-Path $DataRoot 'runtime'))){ Test-DirectoryIo $dir }
    Ensure-PrivateRuntime

    # Keep the saved port as a preference. The V3.3 supervisor will change it
    # automatically only when Windows or another process makes it unusable.
    Refresh-PortFromConfig
    Ensure-Cluster
    Save-Config
    Start-PrivatePostgres
    Refresh-PortFromConfig
    Bootstrap-Database

    Say "[OK] PostgreSQL is ready on 127.0.0.1:$Port."
    Say "[DATA] $DataRoot"
    Say '[MODE] User-managed PostgreSQL process. CampusFace starts it automatically.'
    try { Stop-Transcript | Out-Null } catch {}
    exit 0
} catch {
    Write-Host "[DETAIL] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '[ERROR] CampusFace PostgreSQL setup failed.' -ForegroundColor Red
    Write-Host "[LOG] $Transcript"
    try { Stop-Transcript | Out-Null } catch {}
    exit $script:ExitCode
}
