# Live video without AI recognition — 2026-10-09

## Goal and observed evidence

Identify configured AI admission and distinguish it from live browser video. User confirms Production on Windows at port 8100, with Laptop/Hikvision LIVE, unassigned-store labels, AI disabled and empty recognition panel. Sandbox localhost access is not evidence that the host website is down. Preserve four slots, multi-person tracks, appearances, background AI, security and PAD fail-closed.

## Architecture and proven source gaps

Database camera context owns AI admission: enabled camera, ai_enabled, exactly one valid store and nonempty zone. Live video readers do not enable inference. Workers consume fresh camera frames, publish camera-scoped metadata and business events independently of browser selection. Source review proved AI state ACTIVE could be returned for a connected worker that is paused or has AI_PROCESS_FAILED; successful video publication clears the shared error and failed inference attempts contribute to AI FPS. Selected UI displays generic Ready/wait/0% without explaining known AI availability. Optional YOLO is distinct from required YuNet/SFace/Passive PAD.

## Files and scope

Narrow changes: camera inference telemetry, CameraAIRuntime state, fixed-code-only public status/metadata fields, existing UI labels/panel, focused tests and safe readonly diagnostic CLI/report. No camera defaults, source credentials, registry assignment writes, recognition/PAD thresholds, model changes, capture scheduling, attendance/counting, source handover or database migrations.

## Migration, rollback and privacy

No migration or production data write. Diagnostic DB transactions are explicitly readonly; never initialize/migrate/import the application to inspect customer data. No source/password/session/token/biometrics are selected or emitted. Restore only modified source files to roll back. Configuration changes stay in the authorized Owner/Admin website workflow; do not choose the customer's store or silently enable their cameras.

## Validation

Focused worker status/error/success/empty-scene/source-epoch tests; existing camera AI runtime and lifecycle tests; frontend camera configuration/slots/panel tests; syntax/compile. Diagnostic CLI tested against isolated readonly fixtures and attempted against the local profile without claiming a successful runtime observation when sandbox/network/DPAPI prevents it. Real camera acceptance remains separate. Do not fabricate recognitions or bypass PAD.

## Checkpoints

- [x] Read required project instructions and inspect source/UI evidence.
- [x] Identify source status/error/FPS and unavailable-panel regressions independently.
- [x] Inspect available operational configuration safely; supply host-side readonly diagnostics if needed.
- [x] Implement bounded status/telemetry/UI fixes.
- [x] Run focused tests and source checks; preserve existing camera/PAD contracts.
- [x] Report configuration evidence, source changes, exact enablement steps and real camera acceptance limits.

## Acceptance evidence

Readonly PostgreSQL diagnostic succeeded using the installed Production interpreter. IDs 1/2 (Laptop/Hikvision) have ai_enabled=false, zero store assignments and populated zones; IDs 3/4 likewise AI-disabled/unassigned. Three required model hashes match the supported pins; actual YuNet/SFace/ONNX PAD load in a separate process passed. Optional YOLO files/packages are absent and are not mandatory for YuNet/SFace/PAD. Current browser session/active worker memory and actual frame recognition after authorized enablement were not inspected.

Focused tests: telemetry 9, race 4, admission/latest-frame 12, public/readonly contract 8, selected scoped API 4, private AI stream/source evidence 13 PASS. Node slots 14, configuration 21, adjacent recent 13 and auth routing 11 PASS. Compile 8 Python and syntax 3 JS PASS. Scope-test extraction was updated for the safe public-status helper; raw diagnostic strings remain excluded. Initial readonly test fixture parameter mismatch and Windows stdout encoding were corrected and rerun. No customer configuration was written, no live service was restarted and no fake recognition was supplied.

See `CAMERA_AI_RUNTIME_EVIDENCE_20261009.json` and `FINAL_REPORT_CAMERA_AI_DIAGNOSIS_20261009.md`. Customer must assign the correct store and explicitly enable each desired camera in the existing authorized configuration UI, then perform real camera/FaceID/PAD/background/duplicate acceptance. Do not mark those hardware criteria PASS from unit fixtures.

## Follow-up: both cameras active, missing photos and Hikvision verification

User enabled cameras 1/2 and supplied real UI screenshots. Readonly PostgreSQL now confirms both eligible. Hikvision event 1003 was RECOGNIZED with PAD PASS; later events 1009/1012 were blocked by multi-frame PAD (spoof scores .9926/.8423). These classifications do not prove a concurrent-worker defect or a real-world spoof. No PAD/FaceID thresholds, decisions, scheduling or assignments will be changed.

Snapshots for those classified events exist on disk. ANALYZING appearances have no snapshot by the current writer contract. The selected panel unconditionally clears its image even for a verified track; this is a confirmed frontend gap. Recent cards directly load protected URLs and hide all image errors under the same placeholder; the actual browser HTTP result is being requested without credentials.

Scope: existing `app.js` selected photo delegation and `btmh_recent_recognition.js` finite authenticated evidence loading, permission/error placeholders and cleanup. Evidence stays on the existing store-scoped `evidence.view` endpoint; no raw images in metadata, tokens in URLs, new database records or production writes. No image from a different camera/appearance or recorded identity is substituted for a current live track. Release image requests/object URLs on camera change, permission/auth change, navigation, tab suspension and detail close.

Additional steering: Hikvision is slow even when Laptop AI is disabled. Add source-free numeric per-camera PAD/FaceID/FPS/latency metrics and fixed verification-wait codes to the existing protected metadata route, with focused privacy/finite-number tests. This closes an observability gap; it does not change inference performance or establish a scheduling defect. The selected panel can explain PAD/quality waits from these codes. Limit evidence downloads to three in flight with a bounded current-page queue so image loading does not flood the API. Browser HTTP/runtime measurements and fresh hardware acceptance remain pending.

- [x] Confirm current configuration, event classifications and snapshot file existence readonly.
- [x] Connect the selected current track to its authorized saved event photo and make recent image failures actionable.
- [x] Test auth/scope/late-response/resource cleanup and unchanged appearance/live-result contracts.
- [x] Report confirmed causes, browser-dependent limits and real two-camera acceptance.

User expanded scope to realtime tracking and one large recognition camera. Continuation and final evidence are in EXECPLAN_REALTIME_RECOGNITION_20261009.md and FINAL_REPORT_REALTIME_RECOGNITION_20261009.md; do not rerun the original disabled-camera diagnosis. Latest user host sample confirms ACTIVE/fresh results but no tracks/PAD/FaceID jobs with a face reportedly present in LIVE. Actual AI input/detection/stage samples after changes remain required to establish the Hikvision root cause. Original configuration/model results above are dated historical evidence.
