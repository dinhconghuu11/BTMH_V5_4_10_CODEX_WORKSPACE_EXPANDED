# CampusFace V14 - Offline Core Reliability + Local Action Engine

Version: `1.31.0-v1-face-pro-v14-offline-core-reliability-action`

## Recognition reliability
- Added same-camera recognition deduplication in addition to existing cross-camera guard.
- Kept tracker-centric, event-driven, multi-frame FaceID consensus and identity ownership guard.
- Recognition events returned as deduplicated are not written again to attendance/evidence flows.

## Local Action Engine
- Added temporal episode state machine for HAND_RAISED, PHONE_USE, HEAD_DOWN and MOVING.
- Persistent classroom events are emitted as START/END once per episode instead of on noisy label changes.
- Added DB-side classroom event duplicate guard as a second safety layer.
- Head-down/sleeping weak signal is exposed to customers as prolonged head-down observation, not a claim that a student is asleep.
- Stable SEATED/STANDING changes are recorded only after a short confirmation period.

## Performance
- Action AI adapts FPS and pose budget to camera/FaceID load.
- Dense classrooms reduce Action AI cadence before FaceID is affected.
- Action AI pauses during PTZ motion guard and Safe Camera Handover.
- Latest-frame/no-backlog policy is preserved.

## Offline
- Runtime contract explicitly declares cloud AI disabled and local AI pipeline enabled.
- Frontend remains free of external CDN requirements.
- Phone/object detection only loads a local YOLO model if the model file already exists; it does not download at runtime.
