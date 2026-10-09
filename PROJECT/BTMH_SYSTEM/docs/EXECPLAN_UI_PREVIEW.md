# Offline localhost UI Preview — 2026-10-08

## Goal and acceptance
Run the current BTMH website and real authentication/API on Windows without MediaMTX, cameras, model downloads or Internet. A separate launcher binds only 127.0.0.1:8810 and uses a separate SQLite profile. Frontend assets, owner setup/login/logout, navigation, employee/store management, empty reports and QR invitation management must work. Camera/AI/recording, external integrations and biometric capture must clearly report unavailable. QR HTTPS/PAD/approval requirements remain intact.

## Audit and architecture
The completed master task is retained. START_CAMPUSFACE_DEV.bat relaxes MediaMTX only; it still uses operational data, PostgreSQL/model readiness and hardware workers. tests_browser/preview_ui_v550.py is static visual QA and strips authentication/scripts, so cannot meet this request. The real app constructs workers lazily, but production startup seeds cameras and starts capture, inference, gateway, recording and sync. Subsequent API operations can also start hardware. Config and crypto have import-time directory/key side effects: preview isolation must be established before importing the application.

## Scope and protected areas
Add a dedicated launcher/runner and a small validated preview policy module; narrowly branch config environment-file loading, startup/shutdown, health/root and hardware guards. Preserve the normal launcher, run_module.py, native gateway requirement, all business logic, RBAC/auth/QR HTTPS policy, FaceID/PAD thresholds and production data. No install/download, production migration, fake recognition/attendance rows or broad refactor.

## Data and rollback
Only existing additive schema initializers run against PROJECT/BTMH_SYSTEM/.btmh-ui-preview/default. Do not seed cameras or copy operational models/config/data. No new schema/migration. Test profiles are children of .btmh-ui-preview/tests. Stopping the preview restores normal operation; Production remains on its existing launcher/profile. Preview data can be retained for later UI acceptance; this task does not delete any data.

## Security and privacy
Validate development mode, SQLite, loopback binding and fixed preview-root containment before imports; reject aliases/symlinks that escape the private directory. Ignore operational environment files and clear inherited application/integration overrides in the dedicated runner. Retain real auth/RBAC, validation, session cookies and local-only first owner bootstrap. Reject non-loopback clients/Host headers, forwarded proxy assumptions, transport WebSockets and hardware/external integration endpoints. No default password. No biometric publication/capture in this mode; QR capture remains HTTPS-only. Display a persistent UI Preview notice that data is separate and camera/AI unavailable.

## Checkpoints
- [x] Read source/product/master checkpoints; audit existing launchers and import/startup effects.
- [x] Add isolated runner/launcher, validated policy and minimal real-app branches.
- [x] Focused policy/security/production compatibility tests and Python syntax checks.
- [x] Real loopback HTTP smoke: app startup, frontend assets, owner/auth, protected API, safe UI/QR endpoints, hardware unavailable, no fake event/attendance rows, graceful stop.
- [x] Document exact Windows command/URL, limitations and PASS/FAIL/BLOCKED evidence; stop.

## Test plan and acceptance evidence
Use only focused tests. Existing installed Python/runtime is preferred; no dependency installation. In-process Uvicorn thread and stdlib HTTP client avoid unnecessary child processes. Never claim a blocked test passed. Record any Windows sandbox EPERM as BLOCKED; no escalation requested by the agent. Production missing-MediaMTX fail-closed must still be exercised with the existing narrow runtime tests or a focused equivalent. Final evidence will be added after execution.

Completed: 20 policy tests PASS; 8 real HTTP smoke tests PASS, including 3 pages/36 assets, real owner/password/session lifecycle, Manager RBAC, QR invitation and HTTPS rejection, hardware/integration rejection and zero FaceID/attendance/recognition results. Eight changed Python files compile PASS. Actual Windows batch startup and HTTP 200 at 127.0.0.1:8810 PASS; graceful shutdown confirmed. Production missing MediaMTX still raises before database. Final scope review additionally blocked CDN-backed docs/evidence-cleanup endpoint and rejects child reparse/symlink/hardlink redirects before imports. Preview notice appears on all three pages. Get-NetTCPConnection inventory BLOCKED by Windows CIM Access denied; rendered browser QA BLOCKED because tool browser inventory is empty. No dependency download, outside-sandbox command or broader regression run. Detailed files/startup/limitations/evidence: UI_PREVIEW.md. All task servers stopped.

Resume 2026-10-09: source/checkpoint inspected, no implementation remainder/regression found; prior PASS checks retained without rerun. Fresh unchanged Production artifact resolver reports MEDIAMTX_NOT_INSTALLED (BLOCKED_EXTERNAL_ARTIFACT). Git status/diff BLOCKED: no Git CLI or .git in available workspace/canonical root. Documentation updated with commercial-product clarification and final handoff; no installer, business logic, database or independent Antigravity findings changed. Detailed resumed status is in UI_PREVIEW.md.
