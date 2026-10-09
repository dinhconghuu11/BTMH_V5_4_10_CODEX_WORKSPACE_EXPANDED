# Native live video repair — 2026-10-06

## Goal and acceptance
The active Hikvision main stream stays RTSP H.264 → MediaMTX → WHEP/WebRTC → native browser video, independent of AI. No camera resolution/profile is silently changed. Fallbacks name the actual transport and retain an actionable reason. Real Windows acceptance requires at least five minutes, >=15 rendered FPS where hardware permits, target LAN latency <300 ms, no growing delay and no duplicate sessions after navigation/reconnect.

## Observed architecture and failures
Only media v5410 is loaded. Recognition/dashboard/live-monitor prefer native, but errors are swallowed. Grid/fullsize currently poll JPEG. Gateway HTTP and ICE are loopback-only; remote LAN browsers cannot use it. Readiness checks process/socket rather than source health. Python recovery uses the wrong transport name. Negotiation can outlive navigation and old cleanup can close new peers. UI capture FPS can conceal browser stalls. AI already has separate capture/inference/latest-frame workers and must remain intact. Recorder independently pulls the active upstream and exposes its input in process argv.

Runtime audit found no running BTMH/MediaMTX or installed gateway at the standard profile paths on this workspace host. Camera/browser performance is not yet measurable here.

## Change scope
Gateway manager: source/session diagnostics, redacted actionable errors, separate LAN ICE and local signaling, private loopback RTSP relay. New authenticated same-origin WHEP signaling/session routes. Frontend media controller: bounded cancellable negotiation, attempt ownership, clean synchronous local teardown, stall/reconnect handling, explicit fallback and real browser metrics. App and primary grid/fullsize use these metrics and transport. Recorder can share the active gateway upstream via its loopback relay; direct fallback uses stdin rather than secret-bearing argv. Add behavioral regressions and Windows acceptance instructions.

Expected files: module_app/media_gateway_v5410.py, main.py, recording_runtime_v4.py, frontend/js/btmh_media_v5410.js, app.js, btmh_v4.js, camera_tools_v544.js; relevant tests and docs. Installer remains checksum-pinned/offline-friendly; change only if verification identifies a concrete issue.

## Protected areas
No changes to FaceID/PAD/anti-spoof, thresholds, best-shot, attendance, employee data, PostgreSQL schema, authentication policy, RBAC permissions, camera registry or transactional handover. Preserve /101 source quality. AI's own decode is currently an intentional independent consumer; avoid attaching its old handover session to a mutable gateway path.

## Migration and rollback
No schema/data migration. Generated gateway config is rebuilt at next startup. Rollback the changed source files and restart BTMH; registry/credentials remain in the existing storage. Gateway relay is used only when the internal source matches; recorder falls back explicitly when unavailable. Nonprimary cameras without a configured native gateway must report their fallback and must never show the active camera's frames under another label.

## Security/privacy
No camera credentials in browser payloads/storage/logs/config/argv. Keep HTTP/API/RTSP relay loopback-only, protect browser WHEP through camera.live and bind sessions to their creating user. Ephemeral gateway credentials live only in process memory/environment. Allowlist diagnostic fields; do not expose MediaMTX source/config payloads. Network installation needed only for missing test tools or gateway bootstrap; offline runtime after installation stays supported.

## Checkpoints
- [x] Read required project docs and complete source/runtime audit before code edits; report findings to user.
- [x] Create this ExecPlan before implementation.
- [ ] Repair gateway and add source/session health tests.
- [ ] Add authenticated WHEP proxy and bounded user-owned lifecycle.
- [ ] Repair frontend ownership/cancellation/reconnect/diagnostics and primary grid playback.
- [ ] Share recorder upstream when possible and test process secrecy/cleanup.
- [ ] Run narrow native/realtime tests, complete tests_v54, Python compile, JS syntax, release verifier and credential/duplicate audit.
- [ ] Record automated evidence and remaining real-camera acceptance limits.

## Validation evidence
Pending. Python 3.12.10 and Node 24.12.0 are available. pytest initially missing; installed into workspace tooling after sandbox network approval. aiortc and real camera/gateway absent initially. Do not label hardware FPS/latency/codec compatibility or five-minute soak as passed without measurements.
