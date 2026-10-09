# CampusFace Professional V12.1 - Safe Camera Handover

Version `1.29.0-v1-face-pro-v12-operations-safe-handover`.

- Pause FaceID before switching physical camera source.
- Reset `service-camera` tracker, anti-spoof state and transient best-shot/queue during handover.
- Wait for multiple stable frames from the new source before recognition resumes.
- Automatic rollback to the previous source if the new camera cannot stabilize.
- Recognition remains paused if both target and rollback source are unavailable.
- Recognition events now carry the friendly active camera name.
- Cross-camera recognition dedup suppresses a second recognition event for the same student in a short handover window.
- Added handover audit events and visible V12.1 handover state in the Operations Center.
