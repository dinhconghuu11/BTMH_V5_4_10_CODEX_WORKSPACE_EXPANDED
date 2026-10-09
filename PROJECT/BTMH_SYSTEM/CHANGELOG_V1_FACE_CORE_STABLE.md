# V1 FACE CORE STABLE

- Smart installer reuses the existing per-user runtime, models, PostgreSQL cluster and customer data.
- MiniFASNet PAD is an optional enhancement instead of a single point of failure.
- Built-in strict phone/photo carrier detection can block repeated face-inside-device/photo evidence before FaceID when PAD is absent.
- Weak geometry is never a hard block; it only keeps a track in checking state.
- Natural FaceID remains passive: no blink/head-turn/look-at-camera challenge.
- Single-person classroom Pose is refreshed at ~5 FPS for responsive demo/classroom actions.
- Action UI can surface obvious raw pose actions immediately while the smoothed state continues to drive events.
- Phone-use action is now included in the primary Vietnamese action label.
