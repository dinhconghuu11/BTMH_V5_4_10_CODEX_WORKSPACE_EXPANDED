# CampusFace V1.9 Enterprise Production

## Mục tiêu
Gộp hai nhóm yêu cầu thực tế cuối của CampusFace V1: ổn định Classroom theo video thử nghiệm và biến Lịch sử/Check-in thành giao diện vận hành doanh nghiệp.

## 1. Classroom / Action AI
- Tăng thời gian giữ track ngắn hạn khi detector hụt do cúi, ngồi, quay mặt hoặc chuyển tư thế.
- Cho phép reassociation với thay đổi vị trí khuôn mặt lớn hơn trong một khoảng mất ngắn, giúp giữ Track ID và identity cache.
- Track đang ở grace được giữ trên giao diện nhưng không tạo FaceID/Pose evidence giả.
- Mở rộng body ROI lên phía trên đầu để tay giơ cao không bị crop khỏi Pose.
- Nới điều kiện wrist/elbow hợp lý cho trường hợp cổ tay rõ nhưng khuỷu tay visibility thấp.
- Hand-raise latch có attack/release nhanh hơn.
- "Di chuyển" ưu tiên chuyển vị trí thực; chuyển ngồi/đứng bị tách khỏi motion channel.
- Classroom hiển thị bbox người + tên + một hành động, không hiển thị skeleton ở chế độ khách hàng.
- Độ trễ Classroom hiển thị gần với camera-frame-age + thời gian xử lý AI thay vì chỉ timing của một hàm nội bộ.

## 2. Anti-Spoof / Check-in
- Giữ nguyên nguyên tắc: FaceID match không đồng nghĩa check-in.
- Khi FaceID nhận ra người nhưng anti-spoof/liveness fail, sự kiện vẫn giữ student_id/danh tính nhưng kết quả là `SPOOF_BLOCKED` / CHECK-IN FAILED.
- Panel Nhận diện hiển thị họ tên/MSSV của người đã match và badge `Check-in thất bại`, không thay tên bằng "Từ chối xác minh".
- Sự kiện giả mạo lưu `checkin_result=FAILED` và `failure_type=ANTI_SPOOF`.

## 3. Lịch sử & Hoạt động
- Thay trang log cũ bằng dashboard doanh nghiệp.
- KPI: Check-in thành công, Check-in thất bại, Đăng ký FaceID thành công, Giả mạo bị chặn, Khuôn mặt chưa đăng ký.
- Biểu đồ check-in theo giờ trong ngày.
- Phân loại bảo mật: điện thoại/màn hình, ảnh/bề mặt phẳng, liveness thất bại, khác.
- Tabs: Tất cả / Check-in / FaceID / Bảo mật / Lớp học / Hệ thống.
- Drawer chi tiết sự kiện: người, MSSV, lớp, thời gian, camera, FaceID, liveness, lý do, phương thức bị chặn.
- Bộ lọc ngày, lớp, tìm kiếm và xuất CSV.
- Thêm `audit_events` để ghi đăng ký FaceID và lifecycle hệ thống.

## 4. Phạm vi vẫn giữ đúng V1
- Camera tĩnh.
- Local/offline runtime.
- FaceID 2 vòng.
- Tracker-centric / event-driven FaceID / adaptive Action AI.
- Không đưa PTZ vào V1.

## Giới hạn thực tế
- RGB webcam không tương đương camera IR/depth chuyên dụng; secure liveness ưu tiên từ chối khi chưa đủ chắc chắn.
- Các regression test không thay thế kiểm thử lớp 30-50 người thật và không bảo đảm camera laptop có đủ pixel mặt ở hàng xa.
