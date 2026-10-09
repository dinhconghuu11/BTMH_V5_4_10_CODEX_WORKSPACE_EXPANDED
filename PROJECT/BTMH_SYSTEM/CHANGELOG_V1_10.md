# CampusFace V1.10 – Production Ready

V1.10 giữ nguyên lõi V1.9 (camera tĩnh, FaceID 2 vòng, anti-spoof, tracker-centric Classroom, Action AI, History) và bổ sung các phần phục vụ triển khai doanh nghiệp.

## 1. Phiên điểm danh
- Tạo phiên theo tên, lớp, phòng, giờ bắt đầu/kết thúc và số phút cho phép đi muộn.
- Tự khởi tạo danh sách sinh viên theo lớp.
- Check-in hợp lệ tự ghi vào phiên đang hoạt động.
- Phân loại Có mặt / Đi muộn / Chưa có mặt.
- Lần giả mạo bị chặn được cộng riêng, không biến thành check-in thành công.
- Có sổ điểm danh theo phiên và xuất CSV.

## 2. Vận hành hệ thống
- Trang System Health kiểm tra camera, Face Detector, FaceID templates, database, dung lượng, Classroom và backup.
- Runtime & Load Monitor hiển thị Capture FPS, Preview FPS, AI FPS, p95 AI, số track, action latency, dropped frames, reconnect count, DB size, disk free và frame age.
- Self-test không tạo dữ liệu giả và không chiếm camera.

## 3. Camera Setup
- Cấu hình nguồn camera (index/RTSP), backend, độ phân giải, FPS, codec và tốc độ preview.
- Ghi vào `module.env`.
- Thay đổi có hiệu lực sau khi khởi động lại CampusFace để tránh thay nóng gây mất ổn định camera.

## 4. Backup / Restore
- Backup SQLite + FaceID key + module.env vào một ZIP.
- Dùng SQLite backup API để tạo snapshot nhất quán.
- Cho phép tải backup, nhập backup từ máy khác và khôi phục.
- Trước restore tự tạo một backup an toàn `before-restore`.
- Restore yêu cầu khởi động lại để nạp lại khóa FaceID/cấu hình.

## 5. Phân quyền tối thiểu
- Tài khoản local: `ADMIN` và `OPERATOR`.
- Mật khẩu băm PBKDF2-HMAC-SHA256 với salt riêng.
- Admin: cấu hình camera, backup/restore, quản lý tài khoản, xóa sinh viên/đổi consent.
- Operator: có thể vận hành phiên điểm danh.
- Face recognition/check-in vẫn chạy như kiosk local, không phụ thuộc phiên đăng nhập.

## 6. Triển khai Windows
- Giữ `START_HERE_WINDOWS.bat` / `START_CAMPUSFACE.bat`.
- Thêm `CREATE_SHORTCUTS_WINDOWS.bat`.
- Thêm source Inno Setup + `BUILD_SETUP_EXE_WINDOWS.bat` để build `CampusFace_Setup_V1.10.exe` trên Windows sau khi chuẩn bị offline bundle.

## 7. Không thay đổi phạm vi sếp đã chốt
- V1 vẫn là camera tĩnh, local/offline, chưa PTZ.
- Recognition V1.9 được giữ nguyên về luồng chính.
- PTZ tiếp tục là V2.
