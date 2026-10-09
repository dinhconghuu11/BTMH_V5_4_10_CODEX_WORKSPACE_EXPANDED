# CampusFace Recognition Module V1.3 - Stable Clean Fix

- Giữ nguyên pipeline Nhận diện đang hoạt động tốt.
- Xóa lời gọi frontend `renderClassroomRoster()` không tồn tại.
- Gỡ luật CSS cũ ẩn `#page-classroom`; thêm luật active/inactive cuối cùng để tránh regression.
- Làm lại trang Quản lý lớp học theo phạm vi ổn định: camera dùng chung, FaceID, Pose, tracking, thống kê và nhật ký hành động.
- FaceID đăng ký đổi từ 14 bước cứng sang 2 vòng xoay tự nhiên; AI tự lấy 8-10 góc tốt.
- YOLO FarFace training/runtime giữ nguyên, tách khỏi runtime ổn định.
