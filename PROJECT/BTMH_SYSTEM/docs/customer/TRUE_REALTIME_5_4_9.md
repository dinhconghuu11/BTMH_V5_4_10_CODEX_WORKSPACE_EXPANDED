# True Realtime Transport 5.4.9

BTMH 5.4.9 tách đường hiển thị camera khỏi chu kỳ FaceID/PAD và bỏ cơ chế HTTP snapshot polling trên ba màn hình camera chính.

- Cùng máy quản lý: WebSocket ACK bitmap là fast path vì không cần encode thêm một luồng video thứ hai.
- Máy xem trong LAN: WebRTC được ưu tiên khi runtime sẵn sàng.
- Nếu WebRTC không có, hệ thống tự fallback mà không làm mất chức năng camera.
- Luồng nguồn, recording, evidence và Best Shot không bị hạ chất lượng bởi thay đổi transport.

Nghiệm thu thực tế vẫn cần kiểm tra trên Windows + Hikvision vật lý của cửa hàng.
