# CampusFace V1.7 — Test Report

## Kết quả tự động
- 26/26 bộ regression script: PASS.
- Python compileall: PASS.
- JavaScript `node --check`: PASS.
- Import FastAPI app + WebSocket route: PASS.
- ZIP release clean/integrity: chạy lại trước khi đóng gói.

## Test mới V1.7
- Cheap activity probe không kích hoạt với frame cơ thể đứng yên: PASS.
- Thay đổi vùng tay/thân kích hoạt fast lane: PASS.
- Fast hand channel xác nhận tay phải sau hai mẫu Pose nhanh: PASS.
- Stable Pose global throttle không chạy Pose liên tục cho track ổn định: PASS.
- WebSocket preview có send-one-frame / wait-for-ACK backpressure: PASS.
- Frontend có WebSocket primary + latest-JPEG fallback: PASS.

## Regression giữ nguyên
- Nhận diện V1: PASS.
- FaceID hai vòng: PASS.
- Anti-spoof/liveness gate: PASS.
- Xóa sinh viên thu hồi FaceID: PASS.
- Tracker-centric identity cache: PASS.
- Event-driven FaceID identity budget: PASS.
- Action Engine V2 posture/gesture/motion: PASS.
- Deployment/offline contract: PASS.

## Giới hạn kiểm thử
Môi trường build không có đúng webcam Windows và tải 50 người thật. Các test chứng minh logic, contract và chống regression; độ trễ cuối cùng phải benchmark trên laptop/camera triển khai thực tế.
