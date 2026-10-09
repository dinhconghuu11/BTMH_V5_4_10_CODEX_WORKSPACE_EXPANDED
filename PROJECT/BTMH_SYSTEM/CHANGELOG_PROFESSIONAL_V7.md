# CampusFace Professional V7

Version: `1.24.0-v1-face-pro-v7`

## Mục tiêu
Nâng phần Quản lý lớp học từ màn hình quan sát realtime thành quy trình vận hành có thể dùng thực tế: AI tạo quan sát, lưu bằng chứng, giáo viên xác nhận, rồi mới đưa vào báo cáo.

## Thay đổi chính
- Thêm **Pro Classroom V7 / Human Review** trên trang Quản lý lớp học.
- Thêm chọn lớp và các KPI: sĩ số, người trong khung, đã nhận diện, chưa đăng ký, giơ tay, điện thoại, ngủ và số quan sát chờ xác nhận.
- Lưu ảnh bằng chứng JPEG ngoài database tại `Snapshots/Classroom` khi một hành động có ý nghĩa thay đổi.
- Thêm bảng `classroom_event_reviews` mà không thay đổi bảng FaceID lõi.
- Thêm hàng chờ xác nhận với trạng thái `PENDING`, `CONFIRMED`, `DISMISSED`, `NEEDS_ATTENTION`.
- ADMIN/OPERATOR có quyền xác nhận; thao tác được ghi Audit Log.
- Thêm báo cáo CSV theo lớp, tách rõ quan sát AI và quyết định của người dùng.
- Độ tin cậy hành động không còn dùng nhầm FaceID confidence: V7 dùng phone confidence / pose quality / posture confidence tùy loại quan sát.
- Giữ nguyên Camera HD V5, FaceID, anti-spoof, PostgreSQL, backup, student management và Professional V6.

## API mới
- `GET /api/v1/classroom/classes`
- `GET /api/v1/classroom/pro-summary`
- `GET /api/v1/classroom/review`
- `PUT /api/v1/classroom/review/{event_id}`
- `GET /api/v1/classroom/evidence/{event_id}.jpg`
- `GET /api/v1/classroom/report.csv`

## Tương thích dữ liệu
- Không xóa hoặc tạo lại sinh viên/FaceID.
- Migration chỉ thêm bảng review mới bằng `CREATE TABLE IF NOT EXISTS`.
- Ảnh bằng chứng nằm ngoài database để dễ backup/restore và tránh DB tăng kích thước nhanh.
