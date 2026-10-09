$ErrorActionPreference = "SilentlyContinue"
$dataRoot = [string]$env:CAMPUSFACE_DATA_ROOT
if ([string]::IsNullOrWhiteSpace($dataRoot)) { $dataRoot = Join-Path $env:LOCALAPPDATA "CampusFace" }
$ownedMediaMtx = Join-Path $dataRoot "runtime\mediamtx\mediamtx.exe"
Get-CimInstance Win32_Process -Filter "Name='mediamtx.exe'" | ForEach-Object {
  $exe = [string]$_.ExecutablePath
  if ($exe -and ([System.IO.Path]::GetFullPath($exe) -ieq [System.IO.Path]::GetFullPath($ownedMediaMtx))) {
    Write-Host "[V5.4.10] Stopping previous BTMH MediaMTX gateway (PID $($_.ProcessId))..."
    Stop-Process -Id ([int]$_.ProcessId) -Force
  }
}
$connections = Get-NetTCPConnection -LocalPort 8100 -State Listen
if (-not $connections) { exit 0 }
$blocked = $false
foreach ($c in $connections) {
  $pidValue = [int]$c.OwningProcess
  if ($pidValue -le 0) { continue }
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
  $cmd = [string]$p.CommandLine
  $name = [string]$p.Name
  if ($cmd -match "run_module\.py" -or $cmd -match "module_app\.main" -or ($name -match "python" -and $cmd -match "CampusFace")) {
    Write-Host "[V3.3] Stopping previous CampusFace server on port 8100 (PID $pidValue)..."
    Stop-Process -Id $pidValue -Force
    Start-Sleep -Milliseconds 700
  } else {
    Write-Host "[ERROR] Port 8100 is already used by another program (PID $pidValue, $name)."
    Write-Host "[ACTION] Close that program or free port 8100, then start BTMH Face V3.3 again."
    $blocked = $true
  }
}
if ($blocked) { exit 9 }
exit 0
