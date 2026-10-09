# CampusFace V1 FACE

## Context-first anti-spoof

- Device/screen context is evaluated before FaceID on every usable face frame.
- Explicit face-inside-device evidence blocks identity matching/check-in.
- Strong OpenCV full-frame screen/photo carrier fallback works without extra model downloads.
- Optional local YOLO COCO detector hook supports cell phone / TV / laptop / tablet context when `models/yolo11n.pt` and Ultralytics are present.
- Phone detection never blocks merely because a phone exists nearby: the face must be substantially contained by the device.
- Geometry fallback requires multi-frame confirmation before hard block.
- No active liveness challenges: no blink, turn, stop, or look-at-camera requirement.

## Runtime

- Keeps the proven per-user PostgreSQL runtime/data profile from V1.14.3.
- Does not reintroduce Windows Service or ProgramData ACL dependencies.
