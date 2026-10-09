# Development startup and verified offline MediaMTX

## Goal and success criteria

Explicit `BTMH_ENV=development` starts the existing backend/frontend when MediaMTX is absent, with native gateway unavailable and a visible fallback reason. Production remains the default and requires supported MediaMTX. An offline ZIP installer verifies the pinned 1.21.1 archive before extracting or using its executable.

## Current architecture and observed failure

START_CAMPUSFACE.bat checks only DataRoot/runtime/mediamtx/mediamtx.exe and exits before PostgreSQL/backend startup when absent. check_ready.py also treats missing MediaMTX as fatal on Windows. The backend resolves a different environment override. Existing Live View supports native WHEP, Python WebRTC, WebSocket, MJPEG and snapshots.

## Expected changes

Canonical source: START_CAMPUSFACE.bat, START_CAMPUSFACE_DEV.bat, INSTALL_CURRENT_PC_WINDOWS.bat (explicit production mode), scripts/check_ready.py, scripts/check_mediamtx_runtime.py, module_app/mediamtx_runtime.py, module_app/main.py, module_app/media_gateway_v5410.py, frontend media JS/CSS, offline/online bootstrap scripts, three focused pytest files and browser lifecycle tests. Workspace .vscode/tasks.json references canonical launchers; product implementation remains in canonical source. Usage: docs/DEVELOPMENT_MEDIAMTX.md.

## Protected areas

No FaceID/PAD, recognition thresholds, PostgreSQL policy, RBAC, SMS, attendance, employee data, camera-registry persistence or handover changes. No MediaMTX downloads or mirrors during this task.

## Migration and rollback

No database migration. Production remains the default; development is explicit. Restore the changed source/task files to roll back. Offline installation stages verified files before replacing only the MediaMTX runtime; it does not touch customer configuration/data. Existing online installs can reuse their verified DataRoot/downloads ZIP. A bare executable/version marker without pinned ZIP provenance is now rejected; reinstall offline with the official pinned ZIP to supply proof. Keep the retained runtime ZIP.

## Test plan

Focused tests first: development/production startup policy; ordered supported-binary discovery; missing/present gateway status; fallback diagnostics and true transport; installer correct/incorrect hash and unsafe extraction; credential redaction. Then one related camera/media/startup regression run, Python compilation and changed JavaScript syntax checks, and release verification when practical. Do not claim unexecuted checks.

## Security and privacy

Use the existing pinned archive SHA-256. Never execute an unverified installer candidate or version probe. Discovery compares executable bytes with the executable inside a pinned ZIP. Diagnostics cache hashes for efficiency; startup/spawn invalidate both caches and verify fresh bytes (including Windows equal-size edits with restored metadata). Reject unsafe ZIP members and unsupported versions; emit fixed reason codes without camera secrets or executable probe output. Keep gateway credentials in the existing child environment and loopback authenticated control path. Installer locks the source ZIP across verification/extraction/proof copy and validates cleanup/replacement paths.

## Checkpoints

- [x] Read required project documentation and ExecPlan rules.
- [x] Identify launcher/readiness failure and existing fallback architecture.
- [x] Implement shared discovery and explicit startup policy.
- [x] Implement verified offline installation.
- [x] Wire gateway status and visible frontend fallback.
- [x] Run focused checks, then one relevant regression pass.
- [x] Record acceptance evidence and usage instructions.

## Acceptance evidence

Focused checks executed successfully on Windows:

- Startup/discovery plus existing native gateway/runtime/reliability suites: 48 passed initially. After adding fresh verification and its regression case, the startup/discovery module passed 14 tests.
- Offline PowerShell installer integration: 17 passed. Success fixtures substitute the pin only in a disposable test script; the shipped script retains the official pin and no bypass option.
- Batch launcher/readiness/VS Code mode contracts: 6 passed, including real batch control flow in an isolated harness whose service/browser collaborators are stubbed.
- Browser controller lifecycle: 45 passed, JavaScript syntax passed; state-compatibility changes passed the affected cases.

The pre-existing .test_media ZIP is corrupt and has SHA-256 4b8cdf50332e0b7e9905dbbf29755e5a27c5e7f05be0fb850c81dd562aac41c1, so it was not used or executed. Authentic pinned-ZIP installation and real camera Native WebRTC remain external acceptance checks. No MediaMTX download/mirror was attempted.

Final regression executed once: `VERIFY_RELEASE.py` with `BTMH_ENV=production`, isolated SQLite and the workspace test interpreter. Exit code 0; 81 checks passed, 0 failed. V5.4 pytest: 452 tests, 0 failures/errors/skips. Legacy identity/enrollment: 14 tests, 0 failures/errors/skips. Browser lifecycle: 174 tests, 174 passed. All Python compilation and shipped frontend JavaScript syntax checks passed. Report: `docs/VERIFY_RELEASE_RESULTS_V550.json`. No additional full regression rerun was needed.

## Delivered file inventory

- Workspace launcher metadata: `.vscode/tasks.json` at the workspace root.
- Canonical launch/install: `START_CAMPUSFACE.bat`, `START_CAMPUSFACE_DEV.bat`, `INSTALL_CURRENT_PC_WINDOWS.bat`.
- Backend: `module_app/mediamtx_runtime.py`, `module_app/media_gateway_v5410.py`, `module_app/main.py`.
- Scripts: `scripts/check_mediamtx_runtime.py`, `scripts/check_ready.py`, `scripts/install_mediamtx_offline.ps1`, `scripts/ensure_mediamtx_v5410.ps1`.
- Frontend: `frontend/js/btmh_media_v5410.js`, `frontend/css/btmh_media_v5410.css`.
- Tests: `tests_v54/test_mediamtx_development_runtime.py`, `tests_v54/test_mediamtx_offline_installer.py`, `tests_v54/test_mediamtx_launcher.py`, `tests_browser/media_lifecycle.test.cjs`.
- Documentation/results: `docs/DEVELOPMENT_MEDIAMTX.md`, this ExecPlan, `docs/VERIFY_RELEASE_RESULTS_V550.json` (generated by release verification).
