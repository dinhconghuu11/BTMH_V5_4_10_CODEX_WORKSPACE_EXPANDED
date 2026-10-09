# CHANGELOG V1.7 — Realtime Classroom

## Preview
- Thêm `/api/v1/classroom/preview/ws`.
- WebSocket gửi 1 JPEG rồi chờ ACK `next` từ browser trước khi gửi frame tiếp theo.
- Browser luôn hiển thị frame mới nhất; không tích backlog như stream/poll nhanh truyền thống.
- Giữ endpoint `frame_classroom.jpg` làm fallback.

## Action responsiveness
- Classroom scheduler tăng nhịp điều phối nhẹ lên 8 Hz.
- Thêm body ROI activity probe 32x32, mean-centred để giảm nhạy với thay đổi sáng toàn cảnh.
- Khi phát hiện thay đổi tay/thân, track vào fast lane ~1.1 giây.
- Active Pose interval mặc định 0.16 s; new track 0.14 s.
- Giơ tay dùng hysteresis nhanh và được xác nhận sau chuỗi mẫu Pose ngắn thay vì chờ chu kỳ track ổn định.

## Scale
- Pose budget mỗi cycle vẫn giới hạn 2.
- Stable tracks có global throttle mặc định 2 Pose inference/giây tổng.
- Event-driven FaceID và identity cache từ V1.6 được giữ nguyên.

## Không thay đổi
- Giao diện tổng thể.
- Pipeline Nhận diện chính.
- FaceID đăng ký 2 vòng.
- Anti-Spoof/Liveness.
- Camera tĩnh / local / offline scope.
- YOLO FarFace training tách riêng.
