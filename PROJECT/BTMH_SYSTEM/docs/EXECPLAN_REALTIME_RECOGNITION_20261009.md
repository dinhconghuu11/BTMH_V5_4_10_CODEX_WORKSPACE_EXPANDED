# BTMH realtime recognition continuation — 2026-10-09

## Goal and success criteria

Continue the camera-AI checkpoint without discarding changes. Measure the existing pipeline, correct demonstrated tracking/lifecycle defects, connect actual authorized evidence photos, and show one large recognition camera. Preserve four-camera surveillance and background AI admission. Real accuracy, throughput, anti-spoof and commercial acceptance require hardware measurements and are not inferred from mocked tests.

## Current architecture and evidence

Registry-owned camera workers consume fresh latest packets. Hikvision may use a separately decoded, validated substream; live video is a separate main-stream presentation. YuNet detects faces, WalkBy associates observations, independent bounded PAD/FaceID lanes verify them, and appearance/events feed scoped APIs. Metadata WebSocket drives overlay and the selected result. The user reported ACTIVE, 640x360, capture 18.1 FPS, AI 2.8 FPS, 69 ms average/174.1 ms p95, fresh results, empty tracks, zero PAD/FaceID completions, and a face visible in LIVE. This is one sample, not a proven performance cause. Readonly real events include Hikvision PAD PASS/recognized and PAD BLOCKED. Classified snapshots exist; ANALYZING snapshots are absent by contract.

Confirmed gaps: selected panel clears its photo; recent photo errors are hidden. Per-camera telemetry lacks actual AI input mode, detector/observation distinction and stage timing. Association greedily gives high-quality observations first choice of tracks, and scores overlap against previous rather than motion-predicted boxes; deterministic crowded/moving observations will reproduce these risks before correction. Overlay freshness expiry must be checked independently of arrival of another packet. Recognition currently mounts four main presentation sessions.

## Modules / protected areas

Expected: `walkby.py` association and numeric timings only; `camera.py` sample acquisition/scheduling timings; existing pipeline lane counters if needed; `main.py` allowlisted metadata; existing media/recognition slot JS and scoped CSS/HTML; focused tests; safe Windows host measurement script and evidence/report. Reuse existing owners/models/APIs. No schema migration, database/config writes, thresholds/model replacement, authentication/RBAC weakening, attendance/counting changes, installer work, unrelated dashboard/sidebar changes or new AI system. Do not claim smoothing compensates for missing inference.

## Security, migration and rollback

Keep PAD fail-closed, independent model locks, source/session generation, distinct-frame votes, late result discard, evidence permission/store scope and bounded queues. Numeric telemetry excludes credentials, names, embeddings and image data. Host resource measurement emits process name/ID/CPU/memory only, never command lines. No migration. All previous changes remain. A rollback would restore only this task's source from a source checkpoint and restart normally; it must not reset customer data or registry.

## Implementation checkpoints and validation

- [x] Recover camera diagnosis/evidence/report and required project/design instructions; git metadata/CLI unavailable.
- [x] Fix selected/recent authenticated photos; bound downloads; test scope, cancellation and cleanup.
- [x] Add safe per-camera detection/input/quality/PAD/FaceID diagnostics; 42 isolated public/scope tests and 18 pipeline tests PASS.
- [x] Reproduce greedy/motion association defects; improve matching inside existing tracker; preserve identity guards and generation/absence contracts.
- [x] Measure sample/stage/queue wait timings; keep unknown capture/decode/network latency explicitly unknown.
- [x] Correct confirmed stale-overlay expiry and source/camera timestamp guards; preserve coordinate mapping/fullscreen cleanup.
- [x] Switch recognition to one main presentation owner; preserve four slots in surveillance and background worker ownership.
- [x] Run only affected tracking/security/media/slot/photo/appearance/runtime tests and syntax/compile checks.
- [x] Record user host sample and safe CPU/GPU/RAM benchmark instructions; report DONE/PARTIAL/BLOCKED and remaining hardware acceptance.

Additional confirmed acquisition gap: two pre-fix tests fail because main is copied even when a private AI packet is selected, and stale main is copied before rejection. Copy only the selected fresh source now. No scheduler/FPS/resolution or model threshold was changed.

## UI continuation — reference supplied 2026-10-09

The user requests the supplied dark recognition layout: large camera on the left, current recognition details and recent evidence on the right, and camera switching below the player. Change only recognition HTML, scoped presentation CSS and the existing presentation controller. Keep all current IDs, authenticated evidence loading, stale-result expiry, metadata scope and background AI ownership. No production configuration or model changes. The switch strip uses permitted registry records; its selected thumbnail copies an already displayed frame, without opening extra streams or requesting camera snapshots. Other cameras show an explicit camera placeholder until selected.

No migration or deployment restart is needed for these static assets. Preserve previous edits. If rollback is requested later, restore only this continuation's frontend edits, not customer data or previous recognition fixes. Validate switch ownership, permission/auth cleanup and late-frame rejection with focused browser tests; inspect actual static assets at desktop/tablet/mobile sizes using an isolated local browser if available. Preview must contain no invented identities, evidence photos or recognition results. Live Windows/camera acceptance remains separate.

- [x] Implement scoped dark layout and compact detail/history cards.
- [x] Add registry camera switch strip with selected-frame thumbnail and lifecycle cleanup.
- [x] Run affected media/photo/selection tests and JavaScript syntax checks: 102 Node PASS and 4 syntax PASS.
- [x] Record visual checks, remaining limits and refresh instructions: four isolated Chrome layouts PASS at 390/768/1440/1920 px, no API requests or recognition events. Evidence in frontend/.qa_recognition_console; refresh Production with Ctrl+F5. Saved real-camera photos and hardware acceptance remain pending.

## Acceptance evidence for earlier recognition checkpoint

## Follow-up: readable colors and bounded recent-history updates

The user requests easier-to-read recognition colors and reports continuously retrieved recognized/failed history. Confirmed source behavior: a selected-camera history GET every 2.5 seconds even while idle; unchanged cards are rewritten/re-appended; selected pending tracks request an evidence endpoint before classification and photo retries can continue every five seconds. The backend recent route is already one scoped, limited SELECT; AppearanceManager allocates once per physical appearance and updates the same event for classification. The screenshot alone does not prove duplicate physical appearances or a production capacity limit.

Use the existing selected-camera metadata notification to coalesce meaningful appearance/status changes. Automatic history requests are bounded to once per ten seconds, with a thirty-second idle reconciliation and bounded failure backoff; preserve single-flight, current actor/store/camera guards, 20 rows, manual refresh, photo cleanup and background AI independence. Stop automatic retries on 403. Do not fetch selected evidence for pending tracks; cap image auto-retries at three. Keep unchanged DOM nodes and image owners. Use brand warm-white/ivory surfaces, dark readable text and burgundy/gold accents; preserve camera/overlay geometry and the dark video surface. No backend/schema/model/PAD/attendance/#NNNN change, no customer data/config mutation, no capacity claims from mocks.

Expected edits: scoped console CSS/index cache versions, recent controller, the legacy history delegation in app.js, focused browser/visual tests, PRODUCT/DESIGN and report/checkpoint. No migration/restart required for this frontend follow-up. Preserve prior edits; a requested rollback would restore only these frontend changes, never database/camera state. Prove request/DOM/photo regressions before correction; verify bounded synthetic notification bursts, failures, scope/permission cleanup and Chrome computed colors/contrast/layout at four widths. QA must use no real faces or invented recognition results. Production multi-viewer load and physical-appearance churn remain hardware acceptance items.

- [ ] Reproduce unnecessary idle GETs, unchanged DOM writes and pending-photo GETs.
- [ ] Implement bounded/coalesced history, retry limits and readable scoped colors.
- [ ] Run focused lifecycle/photo/selection/privacy tests and actual Chrome visual QA.
- [ ] Record exact request bounds, files, results and remaining production acceptance.

## Follow-up: verified evidence image loading / Hikvision PAD rejection

New user screenshots show a verified recent/detail image still loading, while the live selected panel can display a blocked-face crop. Screenshot 2 explicitly reports PAD_BLOCKED, not a demonstrated wrong FaceID match. Inspect and reproduce browser image loading and dialog polling first. The recent renderer currently creates hidden lazy images and exposes them only in onload, and recreates an open dialog on every automatic poll. Verify these with regression tests before a minimal photo-lifecycle fix. Keep the authenticated API, permission/scope guards, bounded concurrency and object-URL cleanup. Inspect PAD/model/crop contracts and request numeric current-camera metadata; do not infer a false-positive cause from a screenshot or alter thresholds/model/security to force identity.

- [x] Reproduce hidden lazy-image loading and open-dialog poll cancellation: two Node regressions and a real Chrome failure before correction.
- [x] Correct confirmed image defects; 107 Node and a real Chrome photo case PASS, including permission/logout cleanup and manual retry.
- [x] Inspect the safe host sample and PAD/model/result-validity source contracts. The sample is PAD_CHECKING; the BLOCKED cause remains hardware-pending. FaceID admission is preserved. Correct only the confirmed frozen startup FPS telemetry; regression FAIL before fix, 52 Python PASS after fix.
- [x] Update report/checkpoint and Windows acceptance steps. 5 JS syntax/2 Python compile PASS; actual Production protected photo response and PAD accuracy are not accepted from isolated QA.

Host follow-up: the supplied sample now has one detected/observed face, PAD 4 completed/0 errors and one pending job, FaceID 0 completed, PAD_CHECKING. Its 493.9 ms result latency is within the existing 2-second validity limit. This sample does not establish a PAD false-reject cause. Source inspection confirms substream capture_fps is permanently copied from the three-frame startup readiness diagnostic (310.2 in the supplied sample), rather than measured during ongoing capture. Add a focused failing regression, replace only this telemetry with a bounded one-second decoded-frame rate, and include allowlisted PAD scores/status in the existing read-only host benchmark. Do not change capture settings, model votes, result validity or FaceID admission. Validate decoder handover/retirement and telemetry privacy, then record real acceptance as pending.

Photo/slot/config JS: 57 PASS before the new scope. Public/scoped API: 42 PASS. Async bounded queue/security/detection telemetry: 18 PASS in a separate SQLite QA data root. Three required installed model hashes/load previously PASS. Actual protected photo HTTP response, before/after multi-camera timing, GPU utilization, rendered video/overlay latency, crossing/occlusion accuracy and continuous real-camera soak remain unverified. Do not rerun unrelated release/installer suites or relabel historical evidence as new acceptance.

Final gate: 153 Python + 101 Node PASS, two isolated existing identity guard functions PASS, 8 Python compile/5 JS syntax/PowerShell parse PASS. Five regressions demonstrated before correction then PASS. Three outdated legacy cases still FAIL with both old/current association; legacy R2 whole-file import requires removed ClassroomEngine, while its two relevant guard functions PASS in isolation. No security gate softened to pass legacy fixtures. Source/evidence API contracts rerun with existing global httpx appended to QA interpreter path, no install. Host CPU sampling cannot identify Production listener in tool context; no availability conclusion. Geometry microbenchmark shows ~.32 ms median for ten-face global matching versus ~.15 ms archived greedy; no real FPS improvement asserted. See FINAL_REPORT_REALTIME_RECOGNITION_20261009.md and TRACKING_MICROBENCHMARK_20261009.json.
