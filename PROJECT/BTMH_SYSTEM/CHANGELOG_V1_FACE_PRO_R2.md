# CampusFace V1 FACE PRO R2

Version: `1.22.0-v1-face-pro-r2`

R2 is an in-place upgrade of PRO R1. It keeps the current PostgreSQL cluster, FaceID templates, models, photos, backups and per-user data root.

## 1. Camera mode negotiation
- Windows camera plans still prefer DirectShow + MJPG and 1920x1080@30.
- A driver that opens successfully but silently ignores the requested resolution is no longer treated as a valid 1080p mode.
- CampusFace verifies the actual frame size and continues to the next explicit fallback mode when the requested mode was not really applied.
- Runtime status reports actual FOURCC, actual resolution, autofocus/exposure best-effort state and whether a resolution fallback occurred.

## 2. Camera quality watchdog
- A lightweight downscaled frame is sampled periodically; this does not block FaceID or Action AI.
- Exposes sharpness, brightness, contrast and a `GOOD / FAIR / POOR` camera-quality state.
- Produces actionable warnings: `Hình mờ`, `Thiếu sáng`, `Quá sáng`, `Tương phản thấp`.
- System diagnostics and camera settings UI show these metrics so camera/lighting problems are visible before changing AI thresholds.

## 3. Multi-person FaceID identity guard
- A recognized track is periodically re-verified when a good face is available and the identity budget permits it.
- One weak or ambiguous mismatch never changes the locked identity.
- Two consecutive strong, well-separated contradictory matches release the stale lock and force FaceID reacquisition.
- This specifically reduces name swaps when two people cross or the geometric tracker briefly jumps between faces.
- The same registered identity cannot be committed to two simultaneously live tracks from the same camera.

## 4. Classroom phone-use assist
- Classroom Action AI can reuse explicit local object-detector `cell phone`/`tablet` boxes to strengthen the `Sử dụng điện thoại` label.
- The detector is evaluated once per classroom cycle and its existing cache is reused; this avoids running a second independent detector per student.
- A phone must fall inside the conservative body region of a specific face track and implausibly huge boxes are ignored.
- Rectangle/edge geometry heuristics from anti-spoof are intentionally excluded from Action AI, so a book/monitor-shaped rectangle is not enough to label phone use.
- A short ~0.85 s hold reduces one-frame flicker. Pose-based phone cues remain the fallback when the local device detector is unavailable.

## 5. Compatibility and update behavior
- PRO R1 anti-spoof BLOCK recovery is retained unchanged.
- Posture/activity split and Classroom Action AI remain independent from identity recognition.
- `apply_pro_r2_config.py` only adds new defaults for camera quality and identity revalidation; it does not reset customer-selected camera source/resolution or database settings.
- Normal updates reuse the existing Python runtime, PostgreSQL and models.

## Hardware note
Automated tests can verify state machines and software contracts, but real camera sharpness, exposure, supported 1080p modes and multi-person crossing behavior must still be smoke-tested on the target camera/PC.
