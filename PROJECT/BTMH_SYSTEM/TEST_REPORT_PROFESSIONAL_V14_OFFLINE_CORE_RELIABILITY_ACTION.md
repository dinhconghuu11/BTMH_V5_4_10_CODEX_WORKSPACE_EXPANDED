# CampusFace V14 - Test Report

Version: `1.31.0-v1-face-pro-v14-offline-core-reliability-action`

Validated in the build environment:

- Python module compilation: PASS
- Frontend JavaScript syntax: PASS
- V14 offline core reliability + temporal Action Engine contract: PASS
- V12.1 Safe Camera Handover regression: PASS
- Local classroom action geometry/state-machine regression: PASS
- Newest-frame classroom preview regression: PASS
- Recognition UI/passive anti-spoof regression: PASS
- Offline frontend/no external CDN regression: PASS
- Camera recovery regression: PASS
- V14 API import/smoke + offline health contract: PASS

V14-specific runtime checks include:

- Same-camera recognition duplicate blocking.
- Cross-camera recognition duplicate blocking.
- Classroom action DB duplicate blocking.
- Temporal HAND_RAISED / PHONE_USE / HEAD_DOWN confirmation.
- START/END episode semantics.
- Adaptive Action AI FPS/pose budget under HIGH load and 50 visible tracks.
- Offline runtime declaration (`internet_required_at_runtime=false`, `cloud_ai_used=false`).
- PTZ-motion Action AI pause contract.

Legacy release tests that hard-code older version strings/UI labels are intentionally not used as V14 release gates.
