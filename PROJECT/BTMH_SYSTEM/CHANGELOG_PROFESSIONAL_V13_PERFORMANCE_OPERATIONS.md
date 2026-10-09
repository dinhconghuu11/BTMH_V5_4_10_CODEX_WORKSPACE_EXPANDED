# CampusFace V13 - Performance Operations

Version: `1.30.0-v1-face-pro-v13-performance-operations`

## Performance architecture
- Adaptive AI cadence based on measured inference latency.
- Latest-frame/drop-stale scheduling; no AI frame queue.
- Separate operator preview cadence from AI cadence.
- PTZ motion/focus guard temporarily suspends biometric inference while keeping preview live.
- Realtime metrics: effective target FPS, actual AI FPS, p95 latency, dropped stale-frame ratio, visible faces/tracks.
- Lightweight WebSocket telemetry for Operations Dashboard and Live Monitor.

## Operations UI
- Grouped sidebar: Overview, Attendance, Users, Camera, System.
- Compact System Status Bar.
- Operations-first Dashboard with active camera, recent events and Performance Guard.
- Dedicated Live Monitor with camera registry and AI scheduler telemetry.
- Reduced decorative motion and reduced REST polling frequency.

## Preserved from V12.1
- Safe Camera Handover with pause/reset/settle/resume and rollback.
- Camera & Zone registry, attendance rules, exception review and evidence snapshots.
- PTZ/Digital PTZ, FaceID, anti-spoof, Classroom AI, PostgreSQL, backup and roles.
