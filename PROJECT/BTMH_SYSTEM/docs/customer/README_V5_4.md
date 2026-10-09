# Bảo Tín Mạnh Hải - 5.4.3

**Release Candidate: sửa chuyển module, danh sách camera, sidebar và đăng nhập.**

Nâng cấp từ 5.4.2. Không xóa database, nhân viên, FaceID, tài khoản, lịch sử hoặc cấu hình camera. Không tự bật SMS, không tắt MFA đã kích hoạt.

## Cập nhật

1. Tạo backup bằng chức năng sao lưu trong phần mềm. Không sao chép thư mục PostgreSQL đang chạy để thay cho backup.
2. Chạy `04_DUNG_HE_THONG.bat` của bản cũ; đóng các tab BTMH cũ. Không chạy hai bản cùng lúc.
3. Giải nén toàn bộ Easy Install vào thư mục mới, ví dụ `C:\BTMH_SECURITY_543`. Giữ nguyên `_HE_THONG_BTMH_KHONG_XOA`.
4. Dùng đúng tài khoản Windows cũ, nhấp đúp `01_CAI_DAT_LAN_DAU.bat`. **Không Run as administrator.** Lần cài/cập nhật có thể cần Internet.
5. Chạy `02_KHOI_DONG_HE_THONG.bat`, mở `http://127.0.0.1:8100`, nhấn **Ctrl + F5** để tải JavaScript/CSS mới.
6. Đăng nhập bằng tài khoản hiện có. Không tạo lại Chủ sở hữu. Dữ liệu vẫn ở `%LOCALAPPDATA%\CampusFace` hoặc data root cũ; **không xóa thư mục này**.

## Camera

Trong Nhận diện, bấm **Tải lại**. Danh sách lấy từ Camera Registry, không lọc bỏ USB/PTZ/offline. Camera bị tắt vẫn hiện nhưng không chọn được. Chưa kiểm tra khác với đang online.

Chưa khai báo camera cửa hàng: bấm **Quản lý camera**, nhập đúng nguồn kết nối và lưu. Bản mới không tự tạo camera Hikvision/WyreStorm giả. Không gửi mật khẩu camera/SMS qua chat.

## Kiểm tra sau cập nhật

Cho laptop camera chạy, chuyển qua lại Tổng quan, Nhân sự, Nhận diện, Camera, Lịch sử, Cài đặt. Sau đó chuyển sang IP camera đã khai báo rồi về laptop. Lỗi driver/RTSP/mạng có thể cần xử lý riêng.

`03_KIEM_TRA_HE_THONG.bat` kiểm tra máy cài. `VERIFY_RELEASE.py` dành cho kỹ thuật, cần pytest/Node.js; không bắt buộc cài Node để dùng web.

Xem QA trước nghiệm thu. Chưa kiểm tra Windows/PostgreSQL/camera/SMS thật trong lần phát hành này.
