# YOLO26 FarFace trong CampusFace V1.2

Mục tiêu của YOLO ở V1.2 là **phát hiện/propose khuôn mặt nhỏ, xa hoặc nghiêng**. YOLO không được huấn luyện theo kiểu `mỗi sinh viên = một class`. Danh tính vẫn do SFace + template FaceID đa góc quyết định.

## Dataset nên có
- Ảnh lấy từ chính camera/không gian sẽ triển khai.
- Mặt gần, trung bình, xa; ưu tiên nhiều mặt 24–100 px.
- Chính diện, trái/phải 15–60 độ, cúi/ngẩng.
- Kính, khẩu trang một phần, ánh sáng yếu/ngược sáng và motion blur vừa phải.
- Ảnh nhiều người và nền lớp học thật.

Label YOLO Detect một class `face`: `0 cx cy w h` (normalized 0..1).

## Quy trình
1. `INSTALL_YOLO_TRAINING_WINDOWS.bat` trên máy training có Internet/GPU nếu có.
2. Đưa ảnh/label vào `training/farface_dataset`.
3. Đặt pretrained `yolo26n.pt` vào `training/base_models/yolo26n.pt`.
4. `AUDIT_YOLO_FARFACE_DATASET_WINDOWS.bat`.
5. `TRAIN_YOLO_FARFACE_WINDOWS.bat`.
6. Model tốt nhất được copy thành `models/campusface-face-yolo.pt`.
7. Muốn dùng custom YOLO trong runtime V1, chạy `INSTALL_YOLO_FARFACE_RUNTIME_WINDOWS.bat`. Nếu không chạy, V1 vẫn hoạt động ổn định bằng YuNet + SFace.

**Nguyên tắc ổn định:** huấn luyện YOLO tách khỏi runtime demo. Không cài Torch/Ultralytics vào môi trường V1 nếu chưa cần.
