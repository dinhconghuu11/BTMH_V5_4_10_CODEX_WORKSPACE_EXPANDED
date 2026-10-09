# BTMH 5.5 development handoff — 2026-10-07

Phase 1–6 implementation and Phase 7 automated QA are complete. Production acceptance remains **BLOCKED** for the real hardware, rendered UI and external environments listed below. The product version stays at the existing 5.4.10 development baseline; no final Easy Install was built.

## Automated evidence

| Gate actually run | Result |
| --- | --- |
| Full `tests_v54`, isolated temporary SQLite | **415 passed**, 0 failures/errors/skips |
| Applicable legacy identity/enrollment tests | **14 passed**, 0 failures/errors/skips |
| Browser JavaScript behavior, logical DOM/network/media adapters | **170 passed**, 0 failures/cancellations/skips |
| Release verifier | **81 PASS, 0 FAIL** |
| All 14 frontend JS files, including mobile | Syntax PASS |
| Python source compile | PASS |
| Read-only source/checkpoint audit | **21 PASS, 0 FAIL** |

Numeric suite counts are read from JUnit/TAP in [VERIFY_RELEASE_RESULTS_V550.json](VERIFY_RELEASE_RESULTS_V550.json). [SOURCE_AUDIT_V550.json](SOURCE_AUDIT_V550.json) contains source integrity checks and inventory. Browser adapters prove JavaScript lifecycle contracts; they do not prove rendered CSS or physical video performance.

The first expanded QA run passed all 415 current contracts and 170 browser cases but failed one legacy Vietnamese message assertion. The quality gate AST exactly matched the protected archive. Consistent UTF-8 for Windows Python subprocess writers/readers corrected the test harness; the full rerun passed all 14 legacy tests without modifying the policy. The initial numeric result is retained in [VERIFY_RELEASE_RESULTS_V550_INITIAL.json](VERIFY_RELEASE_RESULTS_V550_INITIAL.json).

## Implemented behavior and principal source files

| Phase | Result and principal files |
| --- | --- |
| 1 — AI pipeline | Independent bounded PAD/FaceID lanes, latest work, stale-generation/frame guards and validated registry-bound AI capture. `ai_pipeline_v550.py`, `ai_capture_v550.py`, `walkby.py`, `camera.py`, `camera_handover_v544.py`, `camera_profiles.py`, `config.py`; FaceCore only model lock boundaries and Passive PAD only CPU/CUDA dispatch fixes. |
| 2 — Adaptive video | Native main/small quality, proven derived small source, owned WHEP sessions and explicit main fallback; main recording/evidence preserved. `media_gateway_v5410.py`, `main.py`, `btmh_media_v5410.js`, `btmh_v4.js`. |
| 3 — Reliability | Decoder/gateway retirement proof, failed-owner retention, bounded retries, reader leases, registry invalidation and source/freshness guards. `capture_session_v544.py`, `camera_fleet_v4.py`, primary camera/handover, gateway and API modules. |
| 4 — Diagnostics | Cached numeric/enum allowlist, `system.diagnostics`, no-store, collapsed details and bounded visible polling. `performance_diagnostics_v550.py`, `main.py`, `btmh_diagnostics_v550.js`, `app.js`. |
| 5 — UI/UX | Shared burgundy/gold/ivory tokens/components, official assets preserved, locked/hidden CSS guards, named controls and auth shell inert. `PRODUCT.md`, `DESIGN.md`, `btmh_design_v550.css`, `index.html`. Rendered acceptance BLOCKED. |
| 6 — Frontend | Stable keyed media tiles, one stats snapshot per render, metadata continuity, stop-before-detach, abort/generation ownership, URL/timer cleanup, BFCache/enrollment proofs and no hidden legacy metric construction. `app.js`, `btmh_v4.js`, `btmh_runtime_v543.js` and browser regressions. |
| 7 — QA | Isolated reproducible verifier with numeric reports, source audit, acceptance protocol and this handoff. `VERIFY_RELEASE.py`, `scripts/audit_v550_source.py`, QA/acceptance documents. |

The source audit proves all 151 original config bindings, five protected WalkBy methods and 14 auth/DB/security/PAD-context/SMS modules retain their AST. PAD/FaceCore differences are constrained to the reviewed dispatch/lock boundaries. All 662 checkpoint HTML IDs remain (665 current IDs), script order and native-first transport remain, and RBAC/diagnostics guards remain intact.

Credential scanning found no literal RTSP userinfo or introduced IP/secret candidate. Six unchanged heuristic matches were classified: historical camera mismatch/migration sentinels and password-input ID references. They are not camera defaults or password values. The two named stock camera configs contain no nonempty secret field or RTSP userinfo. The scan excludes customer/runtime/test data and does not output candidate values.

Inventory compares against a source-only checkpoint, not Git history. `not_in_archive` files can predate this run. Git is unavailable and neither workspace nor canonical source has `.git`; no Git status or commit is claimed.

## Remaining acceptance

**BLOCKED:** physical Hikvision main/small/codec/fallback, real MediaMTX native WebRTC, rendered FPS and measured LAN latency, five-minute hardware soak/reconnect, real FaceID/PAD models and GPU throughput, isolated real PostgreSQL, offline Windows runtime, live SMS delivery, and rendered UI/focus/screenshots at 390/768/1440 px. CUA had no connected browser. No hardware or visual PASS is inferred from mocks, source inspection, token contrast or compile.

The reproducible procedure and required evidence are in [LIVE_VIDEO_WEBRTC_WINDOWS_ACCEPTANCE.md](LIVE_VIDEO_WEBRTC_WINDOWS_ACCEPTANCE.md). Targets remain at least 15 rendered FPS where supported, LAN camera-to-screen latency below 300 ms and a five-minute soak with FaceID/PAD/recording enabled. Unknown measurements remain unknown.

## Preserved rollback and data

`backups/CODEX_WEBRTC_PRE_V550_20261006.zip` is unchanged: **210 entries**, CRC valid, SHA-256 `8894f11fcaba3caa9bda541d6b0f19b325dc282685c04f84d743b991f9b61fac`.

No rollback, reset, discard, checkpoint deletion, `.codex_tools` modification, customer database deletion or `%LOCALAPPDATA%\CampusFace` operation was performed. The local static QA server has been stopped; its source preview generator remains available without API/customer data. Any separately authorized rollback restores source only and preserves database/DataRoot/credentials. No final installer has been created.
