param(
  [Parameter(Mandatory = $true)][string]$ZipPath,
  [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'CampusFace')
)

# This installer never downloads files or executes the installed binary.
# Keep the release pin in sync with ensure_mediamtx_v5410.ps1 and Python discovery.
$ErrorActionPreference = 'Stop'
$Version = '1.21.1'
$ArchiveName = 'mediamtx_v1.21.1_windows_amd64.zip'
$ExpectedSHA256 = 'faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23'
$SourceStream = $null
$Archive = $null
$StagePath = $null
$BackupPath = $null
$RuntimeParent = $null

function Assert-NoReparseAncestors([string]$Path) {
  $Cursor = [System.IO.Path]::GetFullPath($Path)
  while ($Cursor) {
    if (Test-Path -LiteralPath $Cursor) {
      $Item = Get-Item -LiteralPath $Cursor -Force
      if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'INSTALL_PATH_REPARSE_POINT: installation paths must not use symbolic links or junctions.'
      }
    }
    $Parent = [System.IO.Path]::GetDirectoryName($Cursor.TrimEnd('\', '/'))
    if (-not $Parent -or $Parent -eq $Cursor) { break }
    $Cursor = $Parent
  }
}

function Remove-InstallTemporaryDirectory([string]$Path) {
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return }
  $Absolute = [System.IO.Path]::GetFullPath($Path)
  $Parent = [System.IO.Path]::GetFullPath($RuntimeParent).TrimEnd('\', '/')
  if ([System.IO.Path]::GetDirectoryName($Absolute) -ne $Parent -or
      [System.IO.Path]::GetFileName($Absolute) -notmatch '^\.mediamtx-(stage|backup)-[a-f0-9]{32}$') {
    throw 'UNSAFE_CLEANUP_PATH: refusing to remove a path outside the installation staging area.'
  }
  Assert-NoReparseAncestors $Absolute
  foreach ($Item in Get-ChildItem -LiteralPath $Absolute -Force -Recurse) {
    if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
      throw 'UNSAFE_CLEANUP_PATH: refusing to remove a symbolic link or junction.'
    }
  }
  Remove-Item -LiteralPath $Absolute -Recurse -Force
}

try {
  if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) {
    throw 'ZIP_NOT_FOUND: the supplied local MediaMTX ZIP does not exist.'
  }
  $ArchivePath = [System.IO.Path]::GetFullPath($ZipPath)
  $RootPath = [System.IO.Path]::GetFullPath($DataRoot)
  $RuntimeParent = Join-Path $RootPath 'runtime'
  $TargetPath = Join-Path $RuntimeParent 'mediamtx'
  Assert-NoReparseAncestors $RuntimeParent
  Assert-NoReparseAncestors $TargetPath

  # Keep one source handle for verification, extraction, and retained proof.
  # FileShare.Read prevents an in-place writer or replacement during installation.
  $SourceStream = [System.IO.File]::Open($ArchivePath, [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
  $Hasher = [System.Security.Cryptography.SHA256]::Create()
  try { $ActualSHA256 = [System.BitConverter]::ToString($Hasher.ComputeHash($SourceStream)).Replace('-', '').ToLowerInvariant() }
  finally { $Hasher.Dispose() }
  if ($ActualSHA256 -ne $ExpectedSHA256) {
    throw 'SHA256_MISMATCH: refusing an archive that does not match the pinned MediaMTX release.'
  }
  $SourceStream.Position = 0
  Add-Type -AssemblyName System.IO.Compression
  $Archive = [System.IO.Compression.ZipArchive]::new($SourceStream,
    [System.IO.Compression.ZipArchiveMode]::Read, $true)
  $Names = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
  $Entries = New-Object 'System.Collections.Generic.List[object]'
  [long]$TotalSize = 0
  foreach ($Entry in $Archive.Entries) {
    $Name = $Entry.FullName.Replace('\', '/')
    $Directory = $Name.EndsWith('/')
    $CleanName = $Name.TrimEnd('/')
    if (-not $CleanName -or $Name.StartsWith('/') -or $Name.Contains(':') -or
        $Name.Contains([char]0) -or $Name.Contains('//')) {
      throw 'UNSAFE_ZIP_ENTRY: an archive entry has an invalid path.'
    }
    foreach ($Part in $CleanName.Split('/')) {
      if (-not $Part -or $Part -eq '.' -or $Part -eq '..' -or
          $Part -match '[<>:"|?*\x00-\x1f]' -or $Part.EndsWith('.') -or $Part.EndsWith(' ') -or
          $Part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
        throw 'UNSAFE_ZIP_ENTRY: an archive entry has an unsafe Windows path.'
      }
    }
    if (-not $Names.Add($CleanName)) { throw 'DUPLICATE_ZIP_ENTRY: duplicate archive paths are not accepted.' }
    $Attributes = [uint32]([int64]$Entry.ExternalAttributes -band 4294967295)
    $UnixKind = ($Attributes -shr 16) -band 61440
    if ($UnixKind -eq 40960 -or ($Attributes -band 1024) -ne 0) {
      throw 'UNSAFE_ZIP_ENTRY: symbolic links and reparse points are not accepted.'
    }
    if (-not $Directory) {
      $TotalSize += $Entry.Length
      if ($Entry.Length -gt 268435456 -or $TotalSize -gt 536870912) {
        throw 'UNSAFE_ZIP_ENTRY: uncompressed archive size exceeds the supported release limit.'
      }
    }
    $Entries.Add([pscustomobject]@{ Entry = $Entry; Name = $CleanName; Directory = $Directory })
  }
  if (-not $Names.Contains('mediamtx.exe')) {
    throw 'MEDIAMTX_EXE_MISSING: the verified archive does not contain mediamtx.exe at its root.'
  }
  New-Item -ItemType Directory -Path $RuntimeParent -Force | Out-Null
  $StagePath = Join-Path $RuntimeParent ('.mediamtx-stage-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $StagePath | Out-Null
  $StagePrefix = [System.IO.Path]::GetFullPath($StagePath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  foreach ($Record in $Entries) {
    $Destination = [System.IO.Path]::GetFullPath((Join-Path $StagePath $Record.Name))
    if (-not $Destination.StartsWith($StagePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw 'UNSAFE_ZIP_ENTRY: an archive entry escapes the staging directory.'
    }
    if ($Record.Directory) { New-Item -ItemType Directory -Path $Destination -Force | Out-Null; continue }
    New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($Destination)) -Force | Out-Null
    $InputStream = $Record.Entry.Open()
    $OutputStream = $null
    try {
      $OutputStream = [System.IO.File]::Open($Destination, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
      $InputStream.CopyTo($OutputStream)
    } finally {
      if ($OutputStream) { $OutputStream.Dispose() }
      $InputStream.Dispose()
    }
  }
  $ExePath = Join-Path $StagePath 'mediamtx.exe'
  if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw 'MEDIAMTX_EXE_MISSING: extracted mediamtx.exe is not a regular file.'
  }
  $ExeSHA256 = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
  $Archive.Dispose()
  $Archive = $null
  $SourceStream.Position = 0
  $ProofStream = [System.IO.File]::Open((Join-Path $StagePath $ArchiveName), [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  try { $SourceStream.CopyTo($ProofStream) } finally { $ProofStream.Dispose() }
  $Version | Set-Content -LiteralPath (Join-Path $StagePath 'VERSION.txt') -Encoding ASCII
  [ordered]@{ version = $Version; archive_sha256 = $ActualSHA256; executable_sha256 = $ExeSHA256 } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StagePath 'INSTALL_RECEIPT.json') -Encoding ASCII
  @(
    'MediaMTX - third-party runtime component',
    ('Version: ' + $Version),
    'License: MIT',
    'Upstream: https://github.com/bluenviron/mediamtx',
    ('Pinned archive SHA-256: ' + $ExpectedSHA256)
  ) | Set-Content -LiteralPath (Join-Path $StagePath 'THIRD_PARTY_NOTICE.txt') -Encoding ASCII
  # Close the source before replacement, allowing reinstall from the retained ZIP.
  $SourceStream.Dispose()
  $SourceStream = $null
  Assert-NoReparseAncestors $TargetPath
  if (Test-Path -LiteralPath $TargetPath) {
    if (-not (Test-Path -LiteralPath $TargetPath -PathType Container)) {
      throw 'INSTALL_TARGET_INVALID: the MediaMTX installation target is not a directory.'
    }
    foreach ($Item in Get-ChildItem -LiteralPath $TargetPath -Force -Recurse) {
      if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'INSTALL_PATH_REPARSE_POINT: the existing installation contains a symbolic link or junction.'
      }
    }
    $BackupPath = Join-Path $RuntimeParent ('.mediamtx-backup-' + [guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $TargetPath -Destination $BackupPath
  }
  try { Move-Item -LiteralPath $StagePath -Destination $TargetPath; $StagePath = $null }
  catch {
    if ($BackupPath -and -not (Test-Path -LiteralPath $TargetPath)) {
      Move-Item -LiteralPath $BackupPath -Destination $TargetPath
      $BackupPath = $null
    }
    throw
  }
  if ($BackupPath) { Remove-InstallTemporaryDirectory $BackupPath; $BackupPath = $null }
  Write-Host ('MediaMTX ' + $Version + ' installed offline after pinned SHA-256 verification. Binary was not executed.')
  exit 0
} catch {
  # Print fixed reason codes, never untrusted ZIP paths or entry names.
  $Message = [string]$_.Exception.Message
  if ($Message -match '^(ZIP_NOT_FOUND|SHA256_MISMATCH|UNSAFE_ZIP_ENTRY|DUPLICATE_ZIP_ENTRY|MEDIAMTX_EXE_MISSING|INSTALL_PATH_REPARSE_POINT|UNSAFE_CLEANUP_PATH|INSTALL_TARGET_INVALID):') {
    Write-Error $Message -ErrorAction Continue
  } else {
    Write-Error 'OFFLINE_INSTALL_FAILED: unable to verify or install the local MediaMTX archive.' -ErrorAction Continue
  }
  exit 1
} finally {
  if ($Archive) { $Archive.Dispose() }
  if ($SourceStream) { $SourceStream.Dispose() }
  if ($StagePath) {
    try { Remove-InstallTemporaryDirectory $StagePath }
    catch { Write-Warning 'INSTALL_CLEANUP_FAILED: the temporary installation directory could not be removed safely.' }
  }
}
