param([string]$TestFilter = '')
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot '../..')).Path
$pgBin = 'C:/Program Files/PostgreSQL/17/bin'
$clusterRoot = Join-Path $projectRoot ('docs/checkpoints/catalog-backend-20261009/pg-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $clusterRoot | Out-Null
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$testPort = $listener.LocalEndpoint.Port
$listener.Stop()
$dataPath = Join-Path $clusterRoot 'data'
$logPath = Join-Path $clusterRoot 'server.log'
$testPython = Join-Path $workspaceRoot '.test_venv/Scripts/python.exe'
$running = $false
function Invoke-TestPg($program, $arguments, $name) {
    $process = Start-Process -FilePath (Join-Path $pgBin $program) -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $clusterRoot ($name + '.txt')) -RedirectStandardError (Join-Path $clusterRoot ($name + '-error.txt'))
    $testProcessHandle = $process.Handle
    if (-not $process.WaitForExit(30000)) { throw "$program timed out" }
    $process.Refresh()
    if ($process.ExitCode -ne 0) { throw "$program failed: $($process.ExitCode)" }
}
try {
    Invoke-TestPg 'initdb.exe' @('-D', "`"$dataPath`"", '--username=btmh_test_admin', '--auth=trust', '--no-locale', '--encoding=UTF8') 'initdb'
    Invoke-TestPg 'pg_ctl.exe' @('-D', "`"$dataPath`"", '-o', "`"-h 127.0.0.1 -p $testPort`"", '-l', "`"$logPath`"", '-w', 'start') 'start'
    $running = $true
    Invoke-TestPg 'createdb.exe' @('-h','127.0.0.1','-p',"$testPort",'-U','btmh_test_admin','-w','btmh_catalog_test_20261009') 'createdb'
    $env:BTMH_CATALOG_TEST_PG_DSN = "host=127.0.0.1 port=$testPort dbname=btmh_catalog_test_20261009 user=btmh_test_admin"
    $env:CAMPUSFACE_DB_MODE = 'sqlite'
    $env:CAMPUSFACE_DATA_ROOT = Join-Path $clusterRoot 'app-test-data'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = Join-Path $projectRoot 'docs/checkpoints/catalog-backend-20261009/python-pg'
    Push-Location $projectRoot
    try {
        $pytestArgs = @('-m','pytest','-q','tests_v54/test_catalog_backend.py','--tb=short',"--junitxml=$clusterRoot/pytest.xml")
        if ($TestFilter) { $pytestArgs += @('-k',$TestFilter) }
        & $testPython @pytestArgs *> (Join-Path $clusterRoot 'pytest.txt')
        $testExit = $LASTEXITCODE
    } finally { Pop-Location }
    Get-Content -LiteralPath (Join-Path $clusterRoot 'pytest.txt') -Encoding UTF8
    Write-Output "PostgreSQL evidence: $clusterRoot"
    if ($testExit -ne 0) { throw "PostgreSQL catalog tests failed: $testExit" }
} finally {
    if ($running) { Invoke-TestPg 'pg_ctl.exe' @('-D', "`"$dataPath`"", '-m','fast','-w','stop') 'stop' }
    Remove-Item Env:BTMH_CATALOG_TEST_PG_DSN -ErrorAction SilentlyContinue
}
