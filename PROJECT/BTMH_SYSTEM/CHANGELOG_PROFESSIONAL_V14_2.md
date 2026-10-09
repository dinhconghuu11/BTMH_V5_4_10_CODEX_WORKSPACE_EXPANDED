# CampusFace V14.2 - Camera Handover Recovery Hotfix

- Fixes Live Monitor/top-bar state mismatch after a failed PTZ switch.
- `recognition_paused` no longer masquerades as an active camera handover in the UI.
- Camera selectors are unlocked as soon as the real handover finishes.
- Re-selecting an already-online camera now clears stale FaceID pause state.
- Runtime automatically reconciles a stale pause once the recovered camera is ONLINE and delivering fresh frames.
- Keeps Safe Camera Handover, rollback, offline runtime, FaceID and Action AI unchanged.
