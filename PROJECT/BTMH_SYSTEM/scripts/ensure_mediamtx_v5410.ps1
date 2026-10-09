param(
  [Parameter(Mandatory=$true)][string]$DataRoot
)
$ErrorActionPreference = "Stop"
$Version = "1.21.1"
$ArchiveName = "mediamtx_v${Version}_windows_amd64.zip"
$ExpectedSha256 = "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23"
$OfficialUrl = "https://github.com/bluenviron/mediamtx/releases/download/v${Version}/${ArchiveName}"
$MirrorUrl = "https://sourceforge.net/projects/rtspsimpleserver.mirror/files/v${Version}/${ArchiveName}/download"
$RuntimeDir = Join-Path $DataRoot "runtime\mediamtx"
$DownloadDir = Join-Path $DataRoot "downloads"
$ArchivePath = Join-Path $DownloadDir $ArchiveName
$ExePath = Join-Path $RuntimeDir "mediamtx.exe"
$VersionPath = Join-Path $RuntimeDir "VERSION.txt"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

function Test-ExpectedHash([string]$Path) {
  if (-not (Test-Path $Path)) { return $false }
  try {
    $actual = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
    return $actual -eq $ExpectedSha256
  } catch {
    return $false
  }
}

# Offline installs retain their pinned ZIP. Reuse that trusted archive without
# treating a version marker alone as proof that an executable is supported.
$RuntimeArchive = Join-Path $RuntimeDir $ArchiveName
if (-not (Test-ExpectedHash $ArchivePath) -and (Test-ExpectedHash $RuntimeArchive)) {
  Copy-Item -LiteralPath $RuntimeArchive -Destination $ArchivePath -Force
}

if (-not (Test-ExpectedHash $ArchivePath)) {
  Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
  $downloaded = $false
  foreach ($url in @($OfficialUrl, $MirrorUrl)) {
    try {
      Write-Host "[INFO] Downloading MediaMTX $Version from trusted release source..."
      $ProgressPreference = "SilentlyContinue"
      Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $ArchivePath
      if (Test-ExpectedHash $ArchivePath) {
        $downloaded = $true
        break
      }
      Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
    } catch {
      Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
    }
  }
  if (-not $downloaded) {
    Write-Host "[ERROR] Could not download/verify MediaMTX $Version."
    Write-Host "[INFO] Required SHA-256: $ExpectedSha256"
    exit 21
  }
}

# Both online and local-ZIP installation use the same pinned, safe extraction.
# The offline child never accesses the network or executes the candidate binary.
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_mediamtx_offline.ps1") -ZipPath $ArchivePath -DataRoot $DataRoot
exit $LASTEXITCODE
