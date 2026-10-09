# BTMH 5.5.0 development from the native-video checkpoint

Date: 2026-10-06. Resumed: 2026-10-07. Execute phases in order; preserve the existing native WebRTC fixes.

## Resume checkpoint (2026-10-07)
Resume finding: Phase 1 was incomplete. Current phase: Phase 7 automated QA complete; external production acceptance BLOCKED. Phase 1-6 source/automated gates passed. Final evidence: FINAL_QA_V550.md and machine-readable QA/source reports.
Historical resume baseline: workspace and canonical source had no `.git` metadata and Git was not available in PATH; a Git status could not be reported. Initial read-only comparison against the rollback archive found six modified files (camera.py, camera_handover_v544.py, camera_profiles.py, config.py, face_core.py, passive_pad.py), two new AI modules, and no missing archived files. At that point WalkBy async integration and registry binding were unfinished; Phase 1 subsequently completed them. The existing cache had 225 node IDs and an empty lastfailed map, so the baseline was rerun with isolated SQLite data rather than treating the cache as a test report.

Protected archive: `backups/CODEX_WEBRTC_PRE_V550_20261006.zip`, 210 entries, CRC verified; SHA-256 `8894f11fcaba3caa9bda541d6b0f19b325dc282685c04f84d743b991f9b61fac`. Preserve this archive without modification or deletion. Hardware MediaMTX/Hikvision/model/GPU and real PostgreSQL integration are BLOCKED until exercised in their respective environments. No final Easy Install output is authorized while core regression fails.

## Goal and acceptance
Keep main /101 H.264 native video, recording and high-quality evidence independent of AI. Prefer validated Hikvision /102 for AI/adaptive small views, never change the camera's own main settings. Detector/tracker must continue while FaceID/PAD run independently with bounded latest work (at most one waiting batch per lane); stale work cannot commit identity/attendance across camera/track generations. Preserve models, thresholds, quality gates, multi-frame liveness and identity rules. Add safe admin diagnostics, then consistent BTMH burgundy/gold/ivory design without camera lifecycle/performance regressions.

Automated acceptance: checkpoint and new AI/capture/security/lifecycle/RBAC regressions, Python compile, JS syntax/behavior and release verification. Hardware acceptance remains separate: Hikvision codec/streams, >=15 rendered FPS where supported, target LAN latency <300 ms and five-minute soak. No hardware PASS without running it. No more MediaMTX/network downloads in this run.

## Current architecture / observed failure
Native /101 MediaMTX/WHEP is primary with explicit legacy fallbacks; lifecycle/owner/camera guards already exist. AI has a latest capture slot and separate thread, but WalkBy holds its state lock through sequential anti-spoof, embeddings and event persistence. Existing tracking, recognition gates, fusion, identity reverify and revocable PAD are mature and must be reused. Detector/embedding share a model lock. CUDA PAD backend dispatch uses the wrong exact label. Best-shot revision can advance without a better image. One decoded main frame feeds AI/preview; /102 does not have an independent owner. Camera transactional handover must remain canonical to /101. Grid rebuilds and old frontend CSS layers need disciplined stabilization before visual work.

## Scope and protected areas
Expected: new bounded AI scheduler, walkby.py, face_core.py (inference lock boundaries only), passive_pad.py (backend dispatch only), camera.py/handover/config/source helpers and substream owner; media gateway adaptive paths/leases if safely needed; main.py admin diagnostics; frontend design tokens/semantic layer and diagnostics/lifecycle; PRODUCT.md, DESIGN.md, tests and acceptance docs. No schema/data migration, no authentication/RBAC weakening, no model/threshold changes, no customer credentials in browser/logs/config/argv, no unnecessary installer/final Easy Install build.

## Security / concurrency invariants
Every async result carries source epoch, session generation, track identity, frame sequence and capture time. PAD votes count distinct completed frames only. A newer outstanding PAD observation prevents older PASS from authorizing a later identity result. Model work cannot hold the central track lock. Reset/absence/deletion discards old completions. Main evidence must be source/timestamp/geometry verified; do not blindly project a moving face from /102 onto stale /101. Queues and result buffers remain bounded. A failed/hung lane fails closed and restarts only after its old owner has exited; never create duplicate inference threads.

## Rollback / migration
Create a source-only pre-v550 checkpoint archive under backups (no runtime/customer data). Rollback restores that archive's source and restarts BTMH; preserve database/DataRoot/credentials and native-video checkpoint. New async/substream/adaptive flags provide scoped troubleshooting without weakening security. No database migration. Do not stamp final production/Easy Install while core regressions fail.

## Ordered checkpoints
- [x] Baseline: rerun checkpoint tests and verify the existing source-only rollback archive.
- [x] Phase 1: bounded independent PAD/identity lanes; validated /102 latest capture; preserve security gates and evidence; add stage metrics and security tests.
- [x] Phase 1 gate: narrow AI/camera regressions pass before advancing.
- [x] Phase 2: main /101 for single/fullscreen/recording/evidence, lightweight validated stream for small views with explicit unavailable fallback; recording remains copy.
- [x] Phase 2 gate: source/quality/identity/lifecycle regressions pass.
- [x] Phase 3: independent component recovery, bounded retry/backoff, fleet reader leases and no duplicate owners/timers.
- [x] Phase 3 gate: failure/recovery/stop/handover regressions pass.
- [x] Phase 4: system.diagnostics-authorized allowlisted backend + hidden technical details with bounded polling; fix system self-test request regression.
- [x] Phase 4 gate: permission/secret/lifecycle tests pass.
- [x] Phase 5: PRODUCT.md/DESIGN.md, shared design tokens/components across all requested modules; preserve IDs/auth/media logic. Rendered visual acceptance BLOCKED.
- [x] Phase 6: DOM/render/request/timer/listener/hidden-stream audit and behavior regressions; visual inspection BLOCKED by unavailable browser.
- [x] Phase 7: full applicable automated QA, release verifier, credential scan and final evidence/limitations/rollback/Windows acceptance report.
- [ ] External production acceptance: real camera/gateway/models/GPU/PostgreSQL/Windows/SMS and rendered UI — BLOCKED, not exercised.

## Test strategy / evidence
Resume baseline `python -m pytest -q tests_v54` completed successfully (225 existing cases, exit 0; 2026-10-07). Sandbox denied reading installed test package contents, so the same command was rerun with the required escalation; no dependencies changed.
Use existing workspace test interpreter/dependencies only, no .codex_tools edits/downloads. Isolate SQLite test data; never use customer runtime data. Mock slow inference with barriers to prove independent progress and bounded replacement, fail-closed PAD/identity sequencing, source-generation guards and unchanged policy. Real model/GPU/Hikvision/native gateway unavailable in this workspace; mark BLOCKED where not exercised. PostgreSQL hardware regression requires a test cluster; retain adapter/schema untouched and distinguish contract tests from real DB integration.

## Phase 1 completed gate (2026-10-07)
Bounded independent model lanes, guarded completions, validated registry-only /102 capture and safe evidence confirmed. Focused checks: 16 async/security + 14 legacy identity/enrollment, 22 capture, 10 PAD/model dispatch, 58 camera/registry cases passed. Existing browser lifecycle: 22 passed. Full release verifier passed 73 checks, including tests_v54, Python compile and eight JS syntax checks. Final registry refresh hooks subsequently passed the 58-case camera/registry suite; they revoke auxiliary /102 on successful registry writes without changing primary source. Hardware remains BLOCKED.

## Phase 2 implementation checkpoint
Keep main /101 for single/fullscreen, recording and evidence. Add a small-view native quality option only for the active registered camera when its derived stream has been proven by current decoded AI packets. Backend must bind WHEP sessions to an allowlisted path/quality with existing user/camera ownership. Frontend grid requests small quality explicitly; fullscreen stays main. If unavailable, keep main native with an explicit quality fallback reason. Derived sources remain server-only; recording relay stays main and stream copy.

## Phase 2 completed gate (2026-10-07)
Root combined API, adaptive/native gateway, owner/epoch, recording and AI camera regressions: 77 passed, 5 existing deprecation warnings. Gateway owner separately ran 78 focused tests including runtime configuration; browser lifecycle: 41 passed, including 15-second backend fallback, bounded cancellation, no duplicate main retry and fullscreen main protection. Auxiliary config/cleanup is bounded outside the primary lock; revoked sessions remain quota-counted until cleaned. Python compile and frontend syntax passed. Hardware remains BLOCKED.

## Phase 3 implementation checkpoint
Prove decoder retirement before releasing ownership; preserve failed retirement for retry. Add expiring reader leases for auxiliary fleet polling/streams, no decoder start from status-only fleet reads, stale JPEG rejection, source-bound streams, registry invalidation and fail-closed handover reservation. Audit existing independent AI/gateway/recording recovery before adding changes; preserve all model/security policies. Gate with deterministic failure, lease, source switch and recovery tests before diagnostics work.

## Phase 3 completed gate (2026-10-07)
Fleet-focused suite: 65 passed; gateway/adaptive/recording suite: 67 passed plus 8 final gateway retirement cases. Root API/source/lease suite initially 36 passed, then added event-loop isolation and moved MJPEG renew/release into the thread pool. Browser lifecycle remains 41 passed, including offline demand bootstrap and cleanup after fleet API failure. First combined verifier found four new primary fixture failures (missing AI capture status); corrected the fixture and an ownership-warning telemetry flag. Rerun: 73 checks passed, 0 failed, including all tests_v54 (15 new capture/primary cases), Python compile and eight JS syntax checks. No hardware acceptance implied.

## Phase 4 implementation checkpoint
Expose system.diagnostics-protected, numeric/enum-allowlisted performance snapshots from cached state only. Do not activate models, GPU probes, gateway HTTP/recovery or fleet leases during a diagnostics read. Unknown measurements stay null. Technical details are collapsed by default and poll only when visible, authorized and open, with one bounded request owner. Preserve ordinary system health and fix self-test Request forwarding; verify authorization, poison-string filtering, passive reads and cancellation before UI redesign.

## Phase 4 completed gate (2026-10-07)
Cached-only performance collector, strict field/number/enum filtering, stable nested snapshots, null unknown/stale measurements, authorized no-store API and self-test Request/audit fix completed. Technical details remain collapsed and use one 8-second request/10-second-after-completion owner; ordinary system health also has permission/visibility/source-generation cancellation and single-flight refresh. Root browser gate: 71 passed (27 new details, 3 system-health lifecycle, 41 media). Release verifier: 73 passed, 0 failed including all tests_v54, compile and eight existing JS syntax checks; new diagnostics JS syntax independently passed. Includes 11 new API/RBAC cases and collector poisoning/concurrency cases. Hardware remains BLOCKED.

## Phase 5 implementation checkpoint
Document product audiences/modules and a consistent burgundy/gold/ivory design system. Add shared tokens and component styles over the existing frontend, retaining every module/ID/permission/media lifecycle and official artwork. Verify local-only static previews at desktop/mobile sizes without activating cameras, models, recorder or customer data. Do not start Phase 6 DOM/render optimization until this UI checkpoint is reviewable.

## Phase 5 completed source/automated gate (2026-10-07)
PRODUCT.md, DESIGN.md and the final scoped stylesheet are reviewable. Independent source review confirms hidden/RBAC/auth guards outrank old display rules and media geometry/layers are unchanged. Auth shell starts inert and follows existing authentication state; icon controls/action headers are named and nested main landmarks removed. HTML source check preserves all checkpoint IDs (665 current IDs) and one main landmark. Browser lifecycle gate rerun: 71 passed, 0 failed; app.js syntax and static-preview Python compile passed. Token contrast calculations are source evidence only. Actual rendered desktop/mobile layout, computed styles, focus and screenshots are BLOCKED: CUA reports no available browser. Preview generator uses actual markup with product scripts removed, no API/customer data. Proceed to Phase 6 implementation; do not claim visual acceptance.

## Phase 6 implementation checkpoint
Keep grid tile DOM/media owners stable when only name/zone/recording/online metadata changes. Remount only for changed camera ownership, enabled state or main/small quality; retire removed/disabled owners before DOM removal. Guard fleet requests and browser enrollment permission continuations by page/auth/generation. Audit bounded runtime requests, single-flight jobs, hidden work, object URLs and idle timers; remove hidden legacy diagnostics rendering. Gate deterministic cancellation/resource/repeated-navigation behavior before final QA.

## Phase 6 completed automated gate (2026-10-07)
Root focused gates: 85 media/V4 + 85 runtime/app/diagnostics = 170 passed, 0 failed; changed JS syntax passed. Keyed tiles preserve DOM/media on metadata and small-layout changes, retire disabled/deleted owners before detach, reconcile modal ownership and read media stats once per render. Fleet/sources/presence/playback and browser permission continuations have local generation/abort ownership. Runtime deadlines include bodies even when a producer ignores abort; URLs, slots, listeners and idle timers retire. App stops presentation/clock/global polling on hide/pagehide, resumes one authorized owner set, protects enrollment proofs and both recognition awaits, and no longer builds hidden metrics. Independent review caught and resolved initial-boot timer loss, expected cancellation rejection, second-await stale event and app-before-V4 BFCache order. Existing mature system-page/summary keys remain bounded, noncancelled to avoid overlap in nested legacy callbacks; real rendered layout/performance remains BLOCKED.

## Phase 7 implementation checkpoint
Run full tests_v54 plus applicable legacy identity/enrollment regressions in an isolated SQLite DataRoot, all frontend JS syntax, Python compile and browser behavior. Retain numeric test counts and check results in a reviewable JSON report. Audit archive integrity, unchanged preexisting config/policy/security modules, new/modified source inventory and credential hygiene without printing sensitive values. Final report must distinguish automated PASS from BLOCKED real hardware, models/GPU/PostgreSQL and rendered UI; retain rollback and no final installer.

## Phase 7 automated completion (2026-10-07)
Final verifier: 81 PASS, 0 FAIL; full current contracts 415 passed, legacy identity/enrollment 14 passed, browser behavior 170 passed, no skips. All 14 frontend JS syntax and Python compile passed. First expanded run had one legacy Vietnamese subprocess message failure; policy AST unchanged, fixed Windows UTF-8 harness and full rerun passed. Initial numeric failure report retained. Read-only source audit: 21 PASS; archive hash/210 CRC unchanged, no archived path lost, 151 original config bindings/five policy methods/14 protected modules unchanged, exact dispatch/model-lock normalization and reviewed credential hygiene. See FINAL_QA_V550.md, VERIFY_RELEASE_RESULTS_V550.json and SOURCE_AUDIT_V550.json. No further functional changes after these gates. External production/visual/hardware acceptance remains BLOCKED; no final Easy Install.
