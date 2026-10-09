param([string]$Root = (Split-Path $PSScriptRoot -Parent))
$ErrorActionPreference = 'Stop'
try {
  if (-not [Environment]::Is64BitOperatingSystem) { throw 'WINDOWS_X64_REQUIRED' }
  $Root = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
  $Prefix = $Root + [IO.Path]::DirectorySeparatorChar
  $ManifestPath = Join-Path $Root 'vendor\offline-bundle-manifest.json'
  if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw 'OFFLINE_MANIFEST_MISSING' }
  $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
  if ($Manifest.schema -ne 1 -or $Manifest.product -ne 'BTMH' -or $Manifest.version -ne '5.4.10' -or $Manifest.dependency_resolution -ne 'PASS') { throw 'OFFLINE_MANIFEST_INVALID' }
  $Names = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  foreach ($File in $Manifest.files) {
    if ($File.path -match '(^[\\/]|:|(^|[\\/])\.\.([\\/]|$))' -or $File.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'OFFLINE_MANIFEST_INVALID' }
    $Path = [IO.Path]::GetFullPath((Join-Path $Root $File.path))
    if (-not $Path.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase) -or -not $Names.Add($File.path)) { throw 'OFFLINE_MANIFEST_INVALID' }
    $Cursor = $Path
    while ($Cursor -and $Cursor.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
      if (Test-Path -LiteralPath $Cursor) {
        if (((Get-Item -LiteralPath $Cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'OFFLINE_REPARSE_POINT' }
      }
      $Cursor = [IO.Path]::GetDirectoryName($Cursor)
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -ne $File.size) { throw 'OFFLINE_PAYLOAD_MISSING_OR_CHANGED' }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $File.sha256) { throw 'OFFLINE_PAYLOAD_HASH_MISMATCH' }
  }
  foreach ($Required in @('vendor/python-3.12.10-amd64.exe', 'vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip', 'vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip.sha256', 'vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip', 'models/face_detection_yunet_2023mar.onnx', 'models/face_recognition_sface_2021dec.onnx', 'models/minifasnet_v2.onnx', 'requirements-runtime.txt', 'requirements-media.txt', 'frontend/index.html', 'scripts/validate_portable_bundle.py')) {
    if (-not $Names.Contains($Required)) { throw 'OFFLINE_MANIFEST_REQUIRED_ENTRY_MISSING' }
  }
  # No additional executable/importable payload or wheel may bypass inventory.
  foreach ($Item in Get-ChildItem -LiteralPath $Root -Recurse -Force -File) {
    $Relative = $Item.FullName.Substring($Prefix.Length).Replace('\', '/')
    if ($Relative -eq 'vendor/offline-bundle-manifest.json') { continue }
    if (-not $Names.Contains($Relative)) { throw 'OFFLINE_UNLISTED_PAYLOAD' }
  }
  $Python = Join-Path $Root 'vendor\python-3.12.10-amd64.exe'
  $Signature = Get-AuthenticodeSignature -LiteralPath $Python
  if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'PYTHON_PUBLISHER_SIGNATURE_INVALID' }
  $Media = Join-Path $Root 'vendor\mediamtx\mediamtx_v1.21.1_windows_amd64.zip'
  if ((Get-FileHash -LiteralPath $Media -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23') { throw 'MEDIAMTX_PIN_MISMATCH' }
  Write-Host '[OK] Offline payload inventory verified before executing an installer. Manifest is integrity evidence, not a release signature.'
  exit 0
} catch {
  $Reason = [string]$_.Exception.Message
  if ($Reason -notmatch '^[A-Z0-9_]+$') { $Reason = 'OFFLINE_BUNDLE_VERIFY_FAILED' }
  Write-Host ('[BLOCKED] ' + $Reason)
  Write-Host '[ACTION] Obtain a complete, verified BTMH offline release. No network fallback will run.'
  exit 2
}
