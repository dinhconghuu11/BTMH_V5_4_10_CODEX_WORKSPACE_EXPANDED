# CampusFace V1.15.0

## Passive anti-spoof before FaceID

- Anti-spoof now runs for every tracked face before any FaceID embedding/ranking.
- Phone/photo faces can be blocked even when they are not registered.
- FaceID is skipped completely for blocked tracks.
- Unknown/Unregistered is emitted only after passive anti-spoof PASS.
- No blink, turn-left/right, stop-walking or look-at-camera challenge.
- UI shows `Nghi giả mạo` / `SPOOF BLOCKED` instead of `Chưa đăng ký` for presentation attacks.
- Security events preserve the passive liveness reason and spoof method.
- PostgreSQL/installer base remains the working V1.14.3 user-managed local runtime.

## Deployment

V1.15 intentionally reuses `%LOCALAPPDATA%\CampusFaceV1142` so a working V1.14.3 installation can upgrade without rebuilding PostgreSQL, Python or AI models.
