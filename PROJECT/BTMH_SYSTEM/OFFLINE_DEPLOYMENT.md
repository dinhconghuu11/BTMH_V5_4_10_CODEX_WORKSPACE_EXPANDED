# BTMH V5.4.10 — Windows x64 offline deployment

The packaging pipeline is implemented; a customer ZIP/EXE is **BLOCKED** until
the payload audit and distribution evidence pass. An inventory is not a release
signature or proof of clean Windows/camera/GPU/phone acceptance. Current actual
acquisition and license obligations: [third-party audit](docs/THIRD_PARTY_DISTRIBUTION_AUDIT_20261009.md).

## Build computer

Use Windows x64 with Python 3.12 and pip supporting `--dry-run --report`.
`PREPARE_PORTABLE_OFFLINE_WINDOWS.bat` acquires pinned wheels from official PyPI
and hash-verified FaceID/PAD models into this source's `models/`. It also obtains
the Python installer and PostgreSQL archive on the build computer. Acquisition
URLs are for the build computer; customer setup must not access the Internet.
No customer database, camera configuration or runtime credentials belong in the
payload. `.qa_production`, databases, private keys, DPAPI files, local `.env`, logs,
backups, tests and virtual environments are excluded from release staging.

Required payload paths:

| Component | Location | Verification |
|---|---|---|
| Python 3.12.10 amd64 | `vendor/python-3.12.10-amd64.exe` | SHA256 `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb`; valid PSF publisher signature |
| PostgreSQL 17.11-3 x64 | `vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip` | **Missing**; upstream acquisition hash/evidence required, with matching `.zip.sha256` sidecar; never invent a vendor digest |
| MediaMTX 1.21.1 amd64 | `vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip` | SHA256 `faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23` |
| Python inference/backend/media packages | `vendor/wheels/*.whl` | All direct pins plus transitive closure, Windows tags, wheel hashes/notices; actual 60-wheel acquisition recorded separately |
| FFmpeg | Inside the `imageio-ffmpeg==0.6.0` Windows wheel | Real x64 executable required; acquired binary is FFmpeg7.1 GPLv3 build, not covered solely by wrapper BSD notice |
| YuNet/SFace/Passive PAD | Three canonical `.onnx` files in `models/` | Fixed supported hashes in `scripts/download_models.py` and offline validator |
| Frontend/backend/configuration scripts | Clean release stage | Local frontend references and per-file SHA256 inventory; no preview data |

`vendor/offline-provenance.json` records actual source URLs, SHA256 and verification
methods. It does not certify redistribution. Each required component needs its
exact `vendor/licenses/<component>/LICENSE.txt` and completed
`DISTRIBUTION_REVIEW.txt`. The FFmpeg directory also needs `SOURCE.txt` identifying
the exact corresponding source/build and how GPL obligations are met. A generic
license label, placeholder notice or locally generated checksum is insufficient.
Missing PostgreSQL and unresolved redistribution evidence currently block builds.

Run `CHECK_OFFLINE_PACKAGE_WINDOWS.bat` or:

```powershell
python -B scripts/validate_portable_bundle.py --report docs/OFFLINE_PAYLOAD_AUDIT_20261009.json
```

After it passes, run `BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat`, or
`BUILD_SETUP_EXE_WINDOWS.bat` with Inno Setup6 installed on the build computer.
Both use the same verified clean stage and integrity manifest. Output names are
`BTMH-V5.4.10-Windows-x64-OFFLINE-<timestamp>.zip` and
`BTMH_Setup_V5.4.10_<timestamp>.exe`. Existing stages are never deleted or reused.
The ZIP supports Zip64. The EXE cannot compile directly from an unverified tree.

## Official MediaMTX ZIP import from another computer/USB

Download [the official 1.21.1 Windows amd64 ZIP](https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/mediamtx_v1.21.1_windows_amd64.zip)
on a connected build computer. Keep filename
`mediamtx_v1.21.1_windows_amd64.zip`; copy it into `vendor\mediamtx\` in the
canonical source. Compare `Get-FileHash -Algorithm SHA256` with
`faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23`
and the [official release checksum file](https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/checksums.sha256).
The authentic archive has already been acquired for this workspace. The small
ZIP under workspace `.test_media` is a rejected fixture and must never be shipped.

To repair MediaMTX alone from a verified local USB archive, after stopping BTMH:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_mediamtx_offline.ps1 -ZipPath "E:\BTMH\mediamtx_v1.21.1_windows_amd64.zip" -DataRoot "$env:LOCALAPPDATA\CampusFace"
```

Use the existing configured data root if it differs. The importer never downloads
or executes the candidate, validates the fixed ZIP hash and safe extraction, and
retains the archive/receipt. Installing MediaMTX alone does not certify production.

## Customer installation, startup and upgrade

1. Receive the completed release and its checksum through the approved delivery
   channel; verify it on transfer. Extract the ZIP into a new product directory,
   or launch the EXE as a **standard Windows user**, without Run as administrator.
   Older installations with generated caches or stale code should use a fresh code
   directory while keeping their separate existing data root. Strict inventory
   does not silently accept extra importable files; setup and production launch
   disable Python bytecode writes. Inno stores its uninstall metadata outside the
   inventoried product payload.
2. Stop the web server with Ctrl+C, then run `STOP_POSTGRESQL_WINDOWS.bat` before
   repair/upgrade. Direct setup and EXE pre-copy guards refuse an active runtime.
   They do not terminate customer processes or delete data.
3. For a ZIP, run `SETUP_OFFLINE_WINDOWS.bat`. Setup verifies the complete manifest,
   rejects changed/missing/unlisted payload, and validates Python's publisher before
   installing the private runtime. All pip operations use `--no-index`; MediaMTX,
   PostgreSQL and all mandatory FaceID/PAD models come from the local payload.
4. Existing data stays under the resolved `%LOCALAPPDATA%\CampusFace` or preserved
   legacy/configured data root. Existing PostgreSQL clusters/credentials are reused;
   setup fails on an invalid credential instead of resetting the customer database.
   Normal application migrations remain the existing additive/idempotent logic.
5. Launch `START_CAMPUSFACE.bat`. Production readiness requires the real supported
   media gateway, FFmpeg, models and database. The launcher prints the actual URL
   only after successful backend startup. Default local URL is
   `http://127.0.0.1:8100`, subject to configured/available port. Logs are under the
   resolved data root's `logs/`.
6. On a fresh database only, use the existing secure first-Owner procedure;
   established databases show Login. Employee QR enrollment still requires an
   Owner/Admin invitation and PENDING review. No default Owner password is shipped.
7. Stop the server with Ctrl+C and private PostgreSQL with its stop script.
   Backup/restore uses the existing application's authorized workflow; a verified
   operational backup is required before an upgrade. Keep the previous code release
   for rollback; never overwrite/restore a live database as a code rollback.

This product uses the existing per-user process supervisor, not a newly installed
Windows service. LAN/phone QR requires configured reachable origin and trusted
HTTPS/certificate; setup cannot manufacture that acceptance. SMS/provider delivery
can require connectivity even when local video/AI/database operate offline.

## Errors and remaining acceptance

`OFFLINE_MANIFEST_MISSING`, payload hash/unlisted errors, missing PostgreSQL
checksum, wrong publisher and model pin failures stop installation. Obtain/rebuild
the complete verified release instead of disabling the check. Active-runtime errors
require orderly shutdown. Read component logs for PostgreSQL/AI/media readiness
failures; do not delete the database or disable PAD/MFA/RBAC to make startup pass.

Actual isolated tests recorded elsewhere cover no-index installation, local
MediaMTX version, model load/PAD probe and API assets/authentication. Clean Windows
installation/restart/upgrade/backup restore, actual PostgreSQL migration/concurrency,
camera RTSP/WebRTC four slots/reconnect/background AI, real faces/spoof/GPU/soak,
phone/HTTPS and full production UI acceptance remain required. No customer
installer or PRODUCTION READY claim is issued while mandatory gates are blocked.
