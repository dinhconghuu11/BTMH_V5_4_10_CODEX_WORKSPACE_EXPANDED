# Camera Registry Repair 5.4.7

Bản này giữ nguyên Camera ID và các chức năng FaceID/PAD/chấm công.

Nếu một camera Hikvision còn đúng endpoint mẫu cũ `192.168.1.200` nhưng máy Windows đã chuyển sang một mạng riêng khác, BTMH sẽ thử tìm candidate có cùng số cuối trong subnet hiện tại. Hệ thống chỉ tự sửa khi **đúng một** candidate phản hồi cổng RTSP đã lưu. Username, password, port và RTSP path được giữ nguyên.

Ví dụ tại hệ thống hiện tại:

- PC: `192.168.10.10`
- record cũ: `192.168.1.200:554`
- candidate: `192.168.10.200:554`

Nếu candidate không phản hồi hoặc có nhiều candidate hợp lệ, BTMH không sửa tự động. Người quản trị vẫn có thể dùng **Sửa kết nối → Lưu & kiểm tra**.

Việc repair không tự chuyển nguồn đang chạy. Safe Handover vẫn kiểm tra camera mới trước khi đổi FaceID sang nguồn mới.
