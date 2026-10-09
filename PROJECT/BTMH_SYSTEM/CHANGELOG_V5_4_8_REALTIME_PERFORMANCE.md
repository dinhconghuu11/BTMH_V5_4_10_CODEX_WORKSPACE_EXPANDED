# BTMH 5.4.8 - Realtime Performance

- Giữ nguyên FaceID/PAD và Camera Registry 5.4.7.
- RTSP native được giới hạn FPS và scale trước raw frame pipe theo profile.
- Profile mặc định `balanced`: decode 18 FPS, max 1280 px; AI 7 FPS / 960 px; preview 15 FPS / max 1280 px / JPEG 78.
- USB camera giữ hành vi cũ.
- Latest-frame policy được giữ nguyên: không queue frame AI.
- Preview/AI metrics hiển thị target và decoder policy để chẩn đoán tải.
- Có thể đổi `BTMH_RTSP_REALTIME_PROFILE=quality|balanced|light` trong module.env.
