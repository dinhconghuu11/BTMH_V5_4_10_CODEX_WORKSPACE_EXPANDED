# Phạm vi theo yêu cầu quản lý - Version 1

## Mục tiêu
Đóng gói module **đăng ký + nhận diện bằng camera tĩnh** sao cho dễ mang sang máy khác để demo/triển khai.

## Có trong V1
1. Quản lý sinh viên.
2. Đăng ký FaceID 2 vòng.
3. Nhận diện camera tĩnh.
4. Anti-spoof/liveness trước check-in.
5. Quản lý lớp học: bbox + tên + hành động đơn giản.
6. Lịch sử nhận diện/hành động.
7. Local/offline runtime và bộ công cụ build gói offline.
8. Tracker-centric + event-driven FaceID + adaptive Action AI để giảm tải lớp đông.

## Không đưa vào V1
- Điều khiển PTZ vật lý.
- Speaker tracking bằng PTZ.
- Các hành vi suy diễn khó kiểm chứng như mất tập trung, nói chuyện riêng, gian lận.

PTZ được để cho Version 2 sau khi có camera/model/protocol thật.

## V1.9 Production hardening
- Giữ phạm vi camera tĩnh, không PTZ.
- Check-in giả mạo: danh tính FaceID có thể được nhận ra nhưng attendance phải FAIL nếu anti-spoof/liveness không đạt.
- Classroom customer view: một bbox/người + tên + hành động; track/danh tính có short grace khi detector hụt.
- Lịch sử doanh nghiệp: Check-in, FaceID, Bảo mật, Classroom, Hệ thống và xuất CSV.
