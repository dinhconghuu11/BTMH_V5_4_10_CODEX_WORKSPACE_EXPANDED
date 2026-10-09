# BTMH 5.4.6 - Camera Registry Persistence Fix

Phạm vi bản vá: lưu kết nối camera, làm mới reader sau khi sửa cấu hình và xác minh ngay cấu hình đã lưu. Không thay đổi FaceID, Passive PAD, chấm công, RBAC hoặc schema nghiệp vụ.

## Thay đổi chính

- Lưu kết nối theo `camera_devices.id`, đọc lại database và chỉ báo thành công khi endpoint vừa lưu khớp chính xác IP/cổng/path đã nhập.
- Khi sửa camera, dừng riêng Live Grid worker và recorder của camera đó để lần mở kế tiếp dùng URI mới; không dừng camera FaceID đang chạy.
- Nếu camera đang là nguồn khởi động đã lưu, cập nhật startup setting sang URI mới nhưng không ép chuyển nguồn ngay.
- Giao diện đổi nút thành **Lưu & kiểm tra**: sau khi lưu, đọc lại cấu hình rồi preflight chính record vừa lưu.
- Nếu IP cũ `192.168.1.200` còn tồn tại ở record Hikvision cũ, giao diện cảnh báo đây là cấu hình mẫu cũ và yêu cầu nhập IP thực tế.
- Xóa địa chỉ IP cũ khỏi helper legacy không còn sử dụng để tránh tái sử dụng nhầm trong tương lai.

## Tiêu chí nghiệm thu trên máy thật

1. Sửa IP camera, bấm Lưu & kiểm tra.
2. Đóng/mở lại hộp Sửa kết nối: IP vẫn giữ nguyên.
3. Tải lại trang và restart BTMH: IP vẫn giữ nguyên.
4. Kiểm tra kết nối dùng đúng IP vừa lưu.
5. Chuyển Laptop -> Hikvision -> Laptop mà web không đứng.
