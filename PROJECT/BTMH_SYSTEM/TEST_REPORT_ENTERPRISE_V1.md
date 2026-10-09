# CampusFace V1 Enterprise Stable - Test Report

## Kết quả tự động

- Python compile: PASS
- JavaScript syntax: PASS
- Regression suites: **27/27 PASS**
- Recognition preservation: PASS
- Enrollment 2 vòng: PASS
- Camera recovery: PASS
- Classroom on/off: PASS
- Tracker-centric identity cache: PASS
- Event-driven FaceID budget: PASS
- Adaptive Action/Pose budget: PASS
- Fast hand lane: PASS
- Pose jitter không trở thành `Di chuyển`: PASS
- Secure anti-spoof gate: PASS
- Phone/photo rectangular carrier block: PASS
- Check-in không phát sinh trước liveness PASS: PASS
- Spoof event không trở thành successful recognition: PASS
- DB phân biệt RECOGNIZED vs SPOOF_BLOCKED: PASS
- Enterprise UI không vẽ skeleton/keypoint: PASS
- WebSocket newest-frame backpressure: PASS
- Release/deployment contract: PASS

## Điều đã cố ý không cam kết

1. Webcam RGB không có IR/depth nên không thể cam kết chống mọi replay/video spoof ở mức thiết bị sinh trắc học chuyên dụng.
2. Tối ưu lớp 50 người phụ thuộc CPU/GPU, độ phân giải và kích thước khuôn mặt thực tế; kiến trúc đã giới hạn inference nặng theo budget nhưng cần benchmark trên lớp thật.
3. YOLO FarFace chưa phải model custom đã train nếu chưa cung cấp dataset thật.
4. PTZ không thuộc Version 1.

## Kịch bản nghiệm thu khuyến nghị trên máy thật

1. Đăng ký 1 sinh viên bằng 2 vòng FaceID.
2. Nhận diện người thật -> liveness challenge -> check-in PASS.
3. Dùng ảnh tĩnh trên điện thoại -> không được có check-in PASS.
4. Dùng ảnh in -> không được có check-in PASS.
5. Classroom: Ngồi / Đứng / Giơ tay / Di chuyển.
6. Bật/tắt Classroom nhiều lần, không làm hỏng Nhận diện.
7. Cho 5-10 người vào frame để kiểm tra tracking/identity cache.
8. Benchmark lớp thật 30-50 người trước khi nghiệm thu hiệu năng quy mô lớn.
