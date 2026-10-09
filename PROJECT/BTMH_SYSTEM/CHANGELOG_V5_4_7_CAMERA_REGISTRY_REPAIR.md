# BTMH 5.4.7 - Camera Registry Repair

- Giữ nguyên Camera ID và toàn bộ FaceID/PAD/chấm công.
- Tự sửa an toàn endpoint Hikvision mẫu cũ khi PC đã chuyển sang subnet LAN khác.
- Chỉ sửa khi endpoint cũ đúng mẫu legacy và chỉ có đúng một candidate cùng /24 hiện tại phản hồi cổng RTSP đã lưu.
- Giữ nguyên username, password đã mã hóa, port và RTSP path.
- Cập nhật startup camera source nếu nó còn trỏ endpoint cũ.
- Không tự sửa nếu có nhiều candidate hoặc không candidate nào phản hồi.
- Loại bỏ tham chiếu tới mật khẩu camera của người dùng khỏi source kiểm tra release.
