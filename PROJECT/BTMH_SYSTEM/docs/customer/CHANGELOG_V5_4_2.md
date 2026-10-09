# Thay đổi 5.4.2 so với 5.4.1

- Bỏ bắt buộc thiết lập Authenticator cho tài khoản chưa bật MFA; bảo toàn MFA đã bật.
- Thêm adapter Twilio Verify, DPAPI current-user, công cụ cấu hình SMS riêng.
- Bổ sung SMS OTP theo số đã xác minh, phiên 5 phút, hạn mức gửi/kiểm tra, không DEMO hay network-fail bypass.
- Tin cậy trình duyệt 30 ngày tùy chọn, danh sách/thu hồi, vô hiệu khi đổi credential.
- 8 mã khôi phục một lần, xác minh lại cho thao tác nhạy cảm.
- Bảng Bảo mật tài khoản, giao diện SMS responsive, không thêm cấu hình SMTP/DEMO cũ.
- Siết cookie/CSRF, không trả token thô qua JSON, auth LAN cần HTTPS.
- Chặn installer/launcher Administrator ngay đầu; sửa README cũ khuyên chạy quyền quản trị.
- 42 test mới, giữ 24 test hợp đồng cũ, 35 mục verify.

Không triển khai SMS bằng USB modem, email OTP, app mobile, MCP mới, hoặc giao diện showroom vàng mới trong bản vá này.
