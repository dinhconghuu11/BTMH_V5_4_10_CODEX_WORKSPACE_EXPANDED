# Checklist nghiệm thu 5.4.2

Thực hiện trên bản sao dữ liệu trước; lưu ngày, máy, người kiểm tra và kết quả. Các mục dưới đây CHƯA được đánh dấu PASS tại máy khách.

- [ ] Sao lưu và phục hồi thử được database/cấu hình/khóa tương ứng.
- [ ] Cập nhật bằng tài khoản Windows thường; Administrator bị chặn ngay.
- [ ] PostgreSQL, nhân viên, camera, FaceID, báo cáo cũ còn đầy đủ; restart PC thành công.
- [ ] Chưa bật MFA: mật khẩu vào hệ thống, không ép cài Authenticator.
- [ ] Authenticator đã bật vẫn phải xác minh; không mất bảo vệ khi nâng cấp.
- [ ] Lưu DPAPI, restart, cấu hình nhà cung cấp được đọc; secret không vào log.
- [ ] Nhận SMS thật trên SIM của chủ tài khoản, mã 6 số; xác minh và lưu mã khôi phục.
- [ ] Trình duyệt mới: chỉ mật khẩu không mở được dashboard; số nhận đúng tài khoản.
- [ ] Mã sai/hết hạn/gửi lại bị xử lý đúng; provider lỗi không báo đã gửi thành công.
- [ ] Tin cậy trình duyệt: sau logout vẫn cần mật khẩu, không cần OTP; thu hồi/xóa cookie lại cần OTP.
- [ ] Mất Internet: mật khẩu + recovery còn dùng được; một mã không dùng hai lần.
- [ ] Thay số/đổi quyền/restore yêu cầu xác minh mới khi tài khoản có MFA.
- [ ] HTTP LAN bị chặn, HTTPS LAN với cấu hình proxy hợp lệ hoạt động; không NAT cổng ra Internet.
- [ ] Kiểm tra camera, GPU/FaceID và backup/restore trên máy thật trước bàn giao.
