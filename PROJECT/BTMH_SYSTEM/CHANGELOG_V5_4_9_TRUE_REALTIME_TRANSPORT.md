# BTMH 5.4.9 - True Realtime Transport

## Mục tiêu
Loại bỏ request-per-frame ở các màn hình camera chính để video không còn bị trễ theo chuỗi HTTP snapshot khi FaceID/PAD hoặc browser đang bận.

## Thay đổi chính
- Thêm frontend media runtime `btmh_media_v549.js`.
- PC quản lý tại `127.0.0.1/localhost` dùng WebSocket ACK-paced: mỗi lần chỉ có 1 frame đang chờ render; frame cũ bị bỏ thay vì xếp hàng.
- Trình duyệt LAN ưu tiên WebRTC nếu `aiortc` sẵn sàng; fallback theo thứ tự WebSocket -> MJPEG -> finite snapshot.
- Recognition, Dashboard và Giám sát trực tiếp chuyển sang media runtime mới.
- Recognition FPS hiển thị FPS thật được browser render, không còn lấy capture FPS để đại diện cho độ mượt giao diện.
- Bounding box nhận diện được vẽ bằng browser canvas từ metadata WebSocket, tách khỏi đường video.
- WebRTC browser copy được giới hạn FPS/chiều rộng riêng; không thay đổi FaceID/PAD input hoặc threshold.
- Quyền media dùng `camera.live`, không giới hạn riêng cho ADMIN.

## Không thay đổi
- FaceID model/threshold.
- Passive PAD / anti-spoof.
- Best Shot / evidence.
- Camera Registry 5.4.7.
- PostgreSQL schema, nhân sự, chấm công, RBAC, SMS.
