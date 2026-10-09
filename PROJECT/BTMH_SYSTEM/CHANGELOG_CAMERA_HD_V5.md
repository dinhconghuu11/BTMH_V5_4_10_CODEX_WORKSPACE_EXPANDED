# CampusFace Camera HD V5

- Classroom browser preview now keeps up to 1920 px native width instead of the V4 1280 px cap.
- Classroom JPEG quality default raised to 94 with optional luma-quality control when OpenCV supports it.
- Browser-only adaptive contrast/brightness and conservative unsharp masking improve classroom visibility without modifying FaceID/PAD/Action-AI input frames.
- Existing persistent V4/legacy camera configs are upgraded once by `apply_camera_hd_v5_config.py`; student data, PostgreSQL and FaceID templates are untouched.
- Fresh configuration defaults use 1920x1080 camera capture and 1920 px classroom preview.
- Classroom UI shows actual capture resolution, preview FPS and camera quality state.
- ACK-paced WebSocket transport remains unchanged, so slow clients do not build a frame backlog.
