@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PG_FILE=postgresql-17.11-3-windows-x64-binaries.zip"
set "PG_DIR=vendor\postgresql"
set "PG_URL=https://get.enterprisedb.com/postgresql/%PG_FILE%"
if not exist "%PG_DIR%" mkdir "%PG_DIR%"
if exist "%PG_DIR%\%PG_FILE%" goto hash

echo [DOWNLOAD] PostgreSQL 17.11 Windows x64 binary archive ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PG_URL%' -OutFile '%PG_DIR%\%PG_FILE%'"
if errorlevel 1 (
  echo [ERROR] PostgreSQL binary archive download failed.
  exit /b 2
)
:hash
for %%F in ("%PG_DIR%\%PG_FILE%") do if %%~zF LSS 20000000 (
  echo [ERROR] PostgreSQL binary archive is unexpectedly small.
  exit /b 3
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-Content -LiteralPath 'vendor\offline-provenance.json' -Raw -ErrorAction Stop | ConvertFrom-Json; $expected=$p.artifacts.postgresql.upstream_sha256; $actual=(Get-FileHash -LiteralPath '%PG_DIR%\%PG_FILE%' -Algorithm SHA256).Hash.ToLowerInvariant(); if($expected -notmatch '^[a-f0-9]{64}$' -or $actual -ne $expected -or -not $p.artifacts.postgresql.verification_method){Write-Host '[BLOCKED] Reviewed upstream acquisition hash missing/mismatched; a self-generated checksum is not provenance.'; exit 4}; Set-Content -LiteralPath '%PG_DIR%\%PG_FILE%.sha256' -Value $actual -Encoding ASCII"
if errorlevel 1 exit /b 4
echo [OK] PostgreSQL archive matches recorded acquisition evidence.
exit /b 0
