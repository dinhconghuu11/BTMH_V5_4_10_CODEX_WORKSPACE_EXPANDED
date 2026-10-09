# BTMH V5.4.10 — Offline UI Preview

Implemented and verified on Windows, 2026-10-08. This is a separate preview of the current real website/backend, not the static visual-QA server. The completed MASTER TASK remains intact.

BTMH is a commercial product. UI Preview is an internal localhost acceptance mode; it does not constitute the commercial Production deployment or installer.

## Start on Windows

Open PowerShell and run:

```powershell
cd C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM
.\START_BTMH_UI_PREVIEW.bat
```

Alternatively double-click `START_BTMH_UI_PREVIEW.bat` in that folder. Keep its terminal open. Wait for `Application startup complete` and `Uvicorn running on http://127.0.0.1:8810`.

Open **http://127.0.0.1:8810/** in Chrome or Edge. `http://localhost:8810/` may also be used; the listener binds IPv4 127.0.0.1 only. Use the explicit 127.0.0.1 URL if localhost resolves to IPv6 on this PC.

On first launch, use the existing local Owner setup form and choose your own username/password. No default account/password is supplied. Production credentials/accounts are not copied. Subsequent launches retain this preview account and its own test data. Account creation remains Owner/Admin managed; public registration remains disabled.

Stop using Ctrl+C. If Windows asks `Terminate batch job (Y/N)?`, answer Y. Close the preview terminal after shutdown. The launcher does not stop an existing Production server, repair PostgreSQL, download/install packages, copy customer config/models/data, or start MediaMTX.

The launcher selects an existing Python runtime, in order:

1. `BTMH_UI_PREVIEW_PYTHON`, if explicitly supplied.
2. `%LOCALAPPDATA%\CampusFace\runtime\venv\Scripts\python.exe`.
3. The existing legacy `CampusFaceV1142` runtime.
4. The workspace `.test_venv\Scripts\python.exe`.

If a runtime/dependency is missing, startup reports BLOCKED/error; it does not install a replacement. An optional override can select another **existing** compatible runtime:

```powershell
$env:BTMH_UI_PREVIEW_PYTHON = 'C:\path\to\existing\python.exe'
.\START_BTMH_UI_PREVIEW.bat
```

If port 8810 is occupied, the launcher fails without killing that process. For a different local port, use the same existing Python with `-B run_ui_preview.py --port 8811`; no host option or external bind is offered.

## Separate data and behavior

The persistent preview profile is **PROJECT/BTMH_SYSTEM/.btmh-ui-preview/default/**. Its database is `data/recognition_module.db` (SQLite), with separate keys/config/photos/models/logs. Focused smoke tests use distinct `.btmh-ui-preview/tests/http-*` profiles. These local files are git-ignored. Preview does not read normal `module.env` files or inherit customer application/camera/integration overrides.

Existing schema initialization is additive and runs only on the private SQLite profile. No new migration/schema was introduced. The existing default store/shift metadata initializes normally. No employees, cameras, FaceID templates, recognition, visitor sessions or attendance results are seeded. Test employee/accounts created by the smoke suite are named as preview tests and exist only in its separate profile; recognition/attendance/FaceID tables remain empty.

Before any product import/write, preview verifies the fixed private data root, development mode, SQLite and loopback host. Existing junctions, symlinks and multiply-linked files in the profile are rejected. The app also rejects non-loopback clients and non-local Host headers. Uvicorn proxy-header trust/reload/multiworker startup is disabled in the separate runner.

The actual frontend/scripts/authentication gate are retained. A persistent burgundy UI PREVIEW notice appears on `/`, `/mobile` and `/enroll`, identifying separate data and unavailable camera/AI.

## What can be accepted in Preview

- Website loading, existing navigation/layout and local assets.
- Local first Owner setup, password validation, real cookie/session login/logout, profile and account screens.
- Existing Owner/Admin account administration and RBAC checks; Manager is denied Owner/Admin and FaceID approval-management routes.
- Employee metadata/consent, stores, work shifts and assignment management within existing permissions.
- Dashboard, recent recognition, history filters, attendance/report screens with truthful empty states; independent report reads/exports use only the preview database.
- QR invitation creation with locally generated QR PNG, request list/detail and non-biometric management actions. Invitation responses explicitly report `capture_https_ready=false` on HTTP localhost.

## What needs real deployment or hardware

Preview deliberately rejects camera configuration/activation/testing, frame/stream/WebRTC/gateway routes, recognition submission, all realtime WebSockets, AI/model initialization, recording, video processing, external sync, SMS/email delivery, backup creation/import/restore and operational diagnostics. The response clearly identifies the feature as unavailable in UI Preview; existing authentication/RBAC can reject unauthorized requests first.

Face capture, PAD/quality checks, biometric approval/activation, actual identification/attendance/counting and recording require installed models/real hardware and their normal operational prerequisites. Native browser camera viewing requires MediaMTX in normal Production. **QR capture additionally requires trusted HTTPS; HTTP localhost does not bypass that policy.** This listener is not accessible from a phone/LAN. Preview can inspect the enrollment screen and invitation UI but cannot complete phone capture or activate a fake FaceID.

Swagger/OpenAPI documentation UI is disabled in Preview so its CDN resources cannot introduce an Internet dependency. The product website uses existing local assets. Operations summary that runs evidence cleanup is unavailable; independent dashboard/report endpoints remain available.

## Files changed for this independent request

All paths below are relative to PROJECT/BTMH_SYSTEM/; no numbered index folder, MASTER task report or Production launcher was edited.

| File | Change |
|---|---|
| `START_BTMH_UI_PREVIEW.bat` | New separate offline launcher; existing runtimes only. |
| `run_ui_preview.py` | New real-app runner; private environment, 127.0.0.1:8810, no proxy/reload/workers. |
| `module_app/ui_preview.py` | New validated preview/data/HTTP/transport policy and notice. |
| `module_app/config.py` | Opt-in validated preview skips operational env files; training stays in private profile. Normal path unchanged. |
| `module_app/main.py` | Preview-only schema startup/shutdown, truthful health, root/mobile notice, hardware guard and offline docs settings. |
| `module_app/production_ops.py` | Optional `seed_cameras=False` for preview; normal default stays True. |
| `module_app/qr_enrollment_routes.py` | Preview notice on enrollment HTML only; capture/security/workflow unchanged. |
| `.gitignore` | Excludes the private preview profiles, keys and accounts. |
| `tests_v54/test_ui_preview_policy.py` | New focused policy/boundary/Production compatibility tests. |
| `tests_browser/smoke_ui_preview.py` | New real loopback HTTP smoke with separate test profile and hardware/network/process sentinels. |
| `docs/EXECPLAN_UI_PREVIEW.md` | Audit, scope, checkpoints and acceptance evidence. |
| `docs/UI_PREVIEW.md` | This startup/acceptance report. |

## Focused validation results

Executed in sandbox using the already installed runtime at `%LOCALAPPDATA%\CampusFace\runtime\venv\Scripts\python.exe`. No dependencies were downloaded and no outside-sandbox execution was requested.

| Check | Result | Evidence |
|---|---|---|
| Preview policy suite | **PASS — 20 tests** | Private profile/environment, descendant redirect rejection, Host/client/WS boundaries, hardware/integration/docs/cleanup denial, original gateway-before-DB Production behavior. |
| Real HTTP smoke | **PASS — 8 tests** | In-process Uvicorn on a real loopback TCP socket; 3 pages and 36 referenced assets HTTP 200; every page shows Preview notice. |
| Real auth/RBAC | **PASS** | Weak password rejected, actual Owner bootstrap/cookie login/logout/relogin, anonymous API 401, Manager Owner/Admin/QR-management access 403. |
| Independent UI/API/QR | **PASS** | Safe dashboard/history/report/stores/employee/account APIs HTTP 200; separate test employee and local QR PNG; HTTP QR redemption 403. |
| Hardware/network/process isolation | **PASS** | Startup worker/model/GPU/child-process sentinels untouched; forbidden API operations rejected; recognition/attendance/FaceID rows remain zero. |
| Production missing MediaMTX | **PASS** | Real original requirement raises MEDIAMTX_NOT_INSTALLED before init_db when Preview is off. |
| Python compile checks | **PASS — 8 changed Python files** | Focused `compileall`; exit 0. No frontend JS source was changed. |
| Actual Windows batch launcher | **PASS** | Started actual `.bat`, startup completed, `/` and health HTTP 200 on 8810; health SQLite/production=false. Graceful shutdown completed after Ctrl+C. |
| OS socket inventory (`Get-NetTCPConnection`) | **BLOCKED** | Windows CIM Access denied, HRESULT 0x80041003. No escalation; runner fixes 127.0.0.1 and Uvicorn confirmed that URL. |
| Rendered Chrome/Edge acceptance | **BLOCKED in tool session** | Browser inventory is empty (`apps:[], browsers:[]`). Website HTTP startup/assets/auth were actually tested; rendered/manual acceptance is still required. |

No remaining focused test FAIL. Existing FastAPI `on_event` deprecation warnings are informational and were not refactored in this small task.

Reproduce the two focused suites from BTMH_SYSTEM with the same existing Python:

```powershell
& "$env:LOCALAPPDATA\CampusFace\runtime\venv\Scripts\python.exe" -B tests_v54/test_ui_preview_policy.py -v
& "$env:LOCALAPPDATA\CampusFace\runtime\venv\Scripts\python.exe" -B tests_browser/smoke_ui_preview.py
```

## Production preservation and final handoff

`START_CAMPUSFACE.bat`, `START_CAMPUSFACE_DEV.bat`, `run_module.py` and the MediaMTX runtime requirement were not changed. Normal config/data/worker startup and default camera seeding remain unchanged when Preview is off. Authentication, RBAC, QR trusted-HTTPS policy, validation, PAD/FaceID thresholds, Production PostgreSQL and all operational data were preserved. No destructive migration, rollback/discard/reset/clean, default password, public registration or fake recognition/attendance results were introduced.

All test servers have stopped. Start the new launcher for acceptance. On Windows/Chrome/Edge manually verify navigation, Owner setup/login/account menu/logout, responsive layout, Preview notice, empty camera slots/history/reports and QR invitation/HTTPS notice. Camera/video/AI/PAD/counting/phone-capture acceptance belongs to normal deployment with its required prerequisites. Implementation and focused checks complete; stop after this report.

## Resume checkpoint — 2026-10-09

Read AGENTS.md, product context, this report and the completed UI Preview ExecPlan; inspected the actual launcher/integration source. No unfinished implementation or new regression was found. Preserved all source/agent changes and reused the executed PASS evidence above; no repeat of the MASTER audit, focused suites or UI polish. This continuation updates documentation only.

- **DONE:** separate launcher/real backend, fixed loopback/private profile, frontend/auth/RBAC/QR invitation checks, unavailable hardware safeguards, focused tests and Windows batch HTTP startup.
- **PARTIAL:** rendered Windows Chrome/Edge acceptance and actual hardware/phone acceptance remain manual; HTTP results do not certify visual rendering or physical operation.
- **BLOCKED_EXTERNAL_ARTIFACT:** a fresh read-only call to the unchanged `resolve_mediamtx()` in Production mode reports `MEDIAMTX_NOT_INSTALLED`, `VERIFIED_BINARY_AVAILABLE=False`. No binary was downloaded, substituted or executed. Production remains fail-closed.
- **BLOCKED:** Git CLI is unavailable and neither workspace root nor canonical source contains `.git`; `git status` cannot run and `git diff` cannot be produced. Files were inspected directly; the 12-file list above describes this independent request, not a claimed Git diff/stat. Prior Windows CIM and connected-browser limitations remain recorded above.
- **Tests:** retain 20 policy + 8 real HTTP smoke PASS and 8 Python compile PASS from 2026-10-08. Broad regression, destructive/data tests and commercial Production/real camera/phone tests are NOT RUN. On 2026-10-09 the read-only MediaMTX artifact check ran successfully and reported the external artifact blocker; suites were not repeated without a source change/regression.

Next commercial work, explicitly outside this task: a separately authorized Production Offline Installer with verified MediaMTX and existing runtime/model dependencies, followed by Windows Production installation and real camera/PAD/attendance/phone HTTPS acceptance. No installer implementation or independent Antigravity findings were changed here. Stop after final handoff.
