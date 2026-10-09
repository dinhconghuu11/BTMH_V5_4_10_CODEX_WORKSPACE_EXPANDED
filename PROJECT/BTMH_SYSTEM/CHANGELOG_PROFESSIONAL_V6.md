# CampusFace Professional Core V6

Version: `1.23.0-v1-face-pro-v6`

## Mục tiêu
Nâng CampusFace từ giao diện demo vận hành lên lõi sản phẩm dễ triển khai tại máy khách mà không thay đổi dữ liệu FaceID hiện có.

## Thay đổi chính
- Thêm trang **Hệ thống** và **Camera Center**: xem camera trực tiếp, độ phân giải thật, FPS, sharpness, brightness, AI p95, reconnect và cảnh báo chất lượng.
- Hiển thị cấu hình camera ngay trên giao diện; giữ cơ chế 1080p -> 720p -> 480p fallback của Camera HD V5.
- Thêm Dashboard Health Strip: Camera, FaceID coverage, Database, Storage, Unknown/Spoof hôm nay.
- Thêm API tổng hợp `/api/v1/dashboard/summary` dùng múi giờ local của máy triển khai cho thống kê “hôm nay”.
- Nâng quản lý sinh viên: ảnh hồ sơ, số góc FaceID, số lần nhận diện, thời điểm nhận diện gần nhất và lịch sử cá nhân.
- Bật nút xuất danh sách sinh viên CSV và tải file CSV mẫu.
- Thêm Timeline sinh viên từ recognition/classroom/audit events.
- Đưa Backup/Restore, tài khoản, phân quyền và audit log ra trang Hệ thống.
- Bổ sung vai trò `VIEWER` (đăng nhập xem, không có quyền thao tác ADMIN/OPERATOR).
- Ghi audit khi tạo/sửa/xóa sinh viên và thay đổi biometric consent.
- Thêm reconnect camera không cần khởi động lại toàn bộ web server (cấu hình driver mới vẫn cần restart process).

## Tương thích dữ liệu
- Không xóa hoặc thay đổi embedding FaceID cũ.
- Không đổi cấu trúc bảng lõi sinh viên/FaceID.
- Tiếp tục dùng `%LOCALAPPDATA%\CampusFace` hoặc data root cũ đã được resolver nhận diện.
