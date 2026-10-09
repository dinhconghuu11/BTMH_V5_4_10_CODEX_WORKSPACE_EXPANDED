# CampusFace V1 Enterprise Stable - Changelog

## Mục tiêu
Chốt Version 1 theo đúng phạm vi camera tĩnh, ưu tiên độ ổn định, triển khai doanh nghiệp và khả năng bảo trì.

## Thay đổi chính so với V1.7

### 1. Classroom UI thực tế hơn
- Bỏ skeleton/keypoint khỏi giao diện khách hàng.
- Chỉ hiển thị 1 hình chữ nhật quanh người.
- Nhãn trên bbox gồm tên + 1 hành động hiện tại.
- Panel theo dõi chỉ hiển thị tên/MSSV + hành động.
- Hành động V1 giới hạn ở: Ngồi, Đứng, Giơ tay, Di chuyển, Chưa xác định.

### 2. Classroom nhẹ hơn
- Preview dùng WebSocket ACK-paced + `createImageBitmap` để giảm overhead ObjectURL/IMG decode.
- HTTP latest-frame vẫn là fallback.
- Preview mặc định 14 FPS / 640 px / JPEG 52.
- Face detector Classroom 5 FPS / 960 px.
- Tracker-centric + event-driven FaceID giữ nguyên.
- Pose/Action ưu tiên người mới/đang hoạt động; người ổn định được xử lý thưa.
- Keypoints không còn gửi ra UI thường, giảm payload JSON.

### 3. Action phản hồi nhanh hơn nhưng đơn giản hơn
- Kênh giơ tay có attack/release nhanh hơn.
- Nhãn khách hàng là một hành động chính, không ghép chuỗi dài.
- `Di chuyển` vẫn dùng lịch sử vị trí theo Track, không coi rung Pose là di chuyển.

### 4. Secure Anti-Spoof
- Mặc định `MODULE_ANTI_SPOOF_MODE=secure`.
- FaceID khớp chưa tạo check-in.
- Check-in yêu cầu active liveness mới (`BLINK_TURN`: chớp mắt + quay nhẹ đầu).
- Phone/photo carrier heuristic vẫn là lớp chặn sớm.
- Nếu fail/timeout -> `SPOOF_BLOCKED`, không ghi check-in.
- UI cập nhật ngay thẻ “Đã chặn giả mạo” để không giữ lại kết quả check-in cũ gây hiểu nhầm.

### 5. Phạm vi sản phẩm
- Camera tĩnh/USB/RTSP tĩnh.
- Không PTZ trong Version 1.
- YOLO FarFace giữ dưới dạng pipeline tùy chọn và môi trường training riêng.
- Có builder cho full offline bundle.
