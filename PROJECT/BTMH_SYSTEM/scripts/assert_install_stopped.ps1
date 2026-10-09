param(
  [Parameter(Mandatory=$true)][string]$InstallRoot,
  [string]$DataRoot = $env:CAMPUSFACE_DATA_ROOT
)
# Read-only refusal guard: never kills a process or edits customer state.
$ErrorActionPreference = 'Stop'
try {
  $InstallRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\', '/') + '\'
  if (-not $DataRoot) {
    $DataRoot = Join-Path $env:LOCALAPPDATA 'CampusFace'
    $LegacyRoot = Join-Path $env:LOCALAPPDATA 'CampusFaceV1142'
    if (-not (Test-Path (Join-Path $DataRoot 'config\module.env')) -and -not (Test-Path (Join-Path $DataRoot 'PostgreSQL\data\PG_VERSION')) -and ((Test-Path (Join-Path $LegacyRoot 'config\module.env')) -or (Test-Path (Join-Path $LegacyRoot 'PostgreSQL\data\PG_VERSION')))) { $DataRoot = $LegacyRoot }
  }
  $RuntimePrefix = [IO.Path]::GetFullPath((Join-Path $DataRoot 'runtime')).TrimEnd('\', '/') + '\'
  foreach ($Process in Get-CimInstance Win32_Process) {
    $Executable = [string]$Process.ExecutablePath
    $CommandLine = [string]$Process.CommandLine
    $InRuntime = $Executable -and $Executable.StartsWith($RuntimePrefix, [StringComparison]::OrdinalIgnoreCase)
    $InInstall = $Executable -and $Executable.StartsWith($InstallRoot, [StringComparison]::OrdinalIgnoreCase)
    $AppCommand = $CommandLine -and $CommandLine.IndexOf($InstallRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $CommandLine -match '(?i)(run_module\.py|uvicorn|mediamtx\.exe)'
    if ($InRuntime -or $InInstall -or $AppCommand) {
      Write-Host '[BLOCKED] ACTIVE_BTMH_RUNTIME: stop the web server/camera workers with Ctrl+C and stop private PostgreSQL with STOP_POSTGRESQL_WINDOWS.bat before installing or upgrading.'
      exit 21
    }
  }
  exit 0
} catch {
  Write-Host '[BLOCKED] INSTALL_PROCESS_CHECK_FAILED: unable to prove the existing runtime is stopped. No process was terminated.'
  exit 22
}
