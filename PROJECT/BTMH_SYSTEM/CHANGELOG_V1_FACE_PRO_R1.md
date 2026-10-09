# CampusFace V1 FACE PRO R1

Version: `1.21.0-v1-face-pro-r1`

This release upgrades the working CORE STABLE baseline without replacing the existing PostgreSQL cluster or Python runtime.

## 1. Recoverable anti-spoof
- A `BLOCKED` track is no longer terminal.
- Anti-spoof continues evaluating every new frame while the track remains visible.
- After the phone/photo carrier disappears for several clean frames and the minimum clean time, state moves `BLOCKED -> CHECKING`.
- Old spoof/PAD votes are cleared at recovery so stale evidence cannot keep the track blocked forever.
- FaceID identity/candidates are cleared on recovery and are reacquired only after anti-spoof returns `PASS`.
- If phone evidence returns during recovery, the clean counter is reset and the track remains blocked.

## 2. Camera quality path
- Fresh/default capture target is 1920x1080 @ 30 FPS.
- Existing 1280x720 default profiles are migrated once to request 1920x1080; the camera service falls back to 1280x720 or 640x480 if hardware rejects 1080p.
- DirectShow + MJPG remains preferred on Windows.
- Best-effort autofocus and auto-exposure are enabled.
- MAX profile can feed the native capture frame directly to recognition while web preview is encoded/resized independently.
- Runtime status exposes actual capture resolution and AI input resolution.

## 3. Classroom Action AI presentation
- Posture and activity are now separate outputs.
- Posture: `Đang ngồi`, `Đang đứng`, `Chưa xác định`.
- Activity: `Ổn định`, `Di chuyển`, `Giơ tay`, `Sử dụng điện thoại`, `Cúi đầu`, `Có dấu hiệu ngủ`.
- Classroom action remains independent from FaceID; identity is attached to an existing track when recognition becomes available.

## 4. Professional persistent storage
- Fresh Windows customers use `%LOCALAPPDATA%\CampusFace` instead of a versioned data folder.
- Existing `%LOCALAPPDATA%\CampusFaceV1142` installations are detected and reused in-place automatically; no data copy/reset is required.
- Program source/update folders remain separate from customer data.

## 5. Student profile photos
- FaceID vectors stay in PostgreSQL.
- After a successful enrollment, only the best quality portrait is persisted outside PostgreSQL at `Photos\Students\<student_id>\profile.jpg` plus `enrollment_best.jpg`.
- PostgreSQL stores only photo metadata/path/hash in `student_photos`.
- Student detail UI can display the profile portrait through a local API.
- Withdrawing biometric consent deletes FaceID templates and enrollment-derived student photos.

## 6. Backup / restore
- Backup continues to use PostgreSQL `pg_dump` for the database.
- `Photos` and optional `Snapshots` are included in the backup archive.
- Restore brings those media trees back alongside database data.

## 7. WebSocket runtime resilience
- The package bundles the pure-Python WebSocket transport used by Uvicorn, so an existing offline runtime does not need a new pip install just for realtime preview.
- The classroom preview uses the ACK-paced newest-frame WebSocket path when available.
- If the transport cannot load for any reason, CampusFace falls back to HTTP newest-frame preview without the previous noisy unsupported-upgrade warning.
- Camera/AI/FaceID remain independent from the transport layer.

## Compatibility
- PostgreSQL database: retained.
- Existing student/FaceID/attendance data: retained.
- YuNet/SFace: retained.
- MiniFASNet remains optional and is not a startup dependency.
- Existing runtime is reused; no repeated long pip/PostgreSQL installation is required for a normal code update.
