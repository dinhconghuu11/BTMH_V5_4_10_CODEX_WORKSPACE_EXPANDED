# TEST REPORT — CampusFace Recognition Module V1 Stable

Kiểm tra source trước khi đóng gói:

- Python compile: PASS.
- JavaScript `node --check`: PASS.
- 10 regression/contract tests: PASS.
- FaceID one/two/three-frame decision policy: PASS.
- Quick re-arm sau khi người rời camera: PASS.
- Camera recovery/fallback logic: PASS bằng fake capture.
- Trang Nhận diện DOM: giữ nguyên byte-for-byte so với base đang chạy tốt: PASS.
- Scanner đăng ký: 2 vòng x 7 mẫu = 14 mẫu thật: PASS.
- Xóa sinh viên -> cascade FaceID + purge cache: contract PASS.
- Classroom action geometry/state machine: đứng/ngồi/giơ tay/cúi đầu/ngủ gật gợi ý/điện thoại gợi ý: PASS bằng dữ liệu pose synthetic.
- Frontend không dùng CDN/cloud: PASS.
- Clean-machine deployment contract: installer offline không phụ thuộc CampusFace cũ; data tách khỏi code: PASS.

## Cần test trên máy Windows thật

Các hạng mục sau phụ thuộc phần cứng/driver nên không thể xác nhận hoàn toàn trong môi trường đóng gói:

- DSHOW/MSMF/MJPG của webcam cụ thể.
- FPS và độ trễ thật ở 640x480 / 1280x720.
- MediaPipe Pose với nhiều sinh viên trong camera thực tế.
- Chất lượng FaceID khi thiếu sáng/mặt nghiêng của camera thật.
- Bộ portable offline sau khi `PREPARE_PORTABLE_OFFLINE_WINDOWS.bat` tải đủ Python installer/wheels/models trên Windows.
