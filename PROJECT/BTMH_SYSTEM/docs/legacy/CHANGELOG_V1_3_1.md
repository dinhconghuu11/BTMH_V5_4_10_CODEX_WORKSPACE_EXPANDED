# CampusFace Recognition Module V1.3.1 - Smooth Classroom

## Muc tieu

Khong thay doi pipeline Nhan dien dang hoat dong tot. Chi sua trang Quan ly lop hoc de nguoi dung tu bat/tat va giam tre hinh tren laptop CPU.

## Thay doi

- Mo trang Quan ly lop hoc: mac dinh **tat**, khong tu dong khoi dong AI/camera preview.
- Nut ro rang: **Bat quan sat** / **Tat quan sat**.
- Classroom preview bo MJPEG lien tuc, chuyen sang **latest-frame polling**. Trinh duyet chi xin frame moi sau khi frame truoc da tai/giai ma xong, vi vay khong tich hang doi frame cu.
- Preview Classroom mac dinh 960 px, JPEG quality 70, muc tieu 10 FPS.
- Khi Classroom bat, FaceID worker duoc gioi han 8 FPS; khi tat, trang Nhan dien tro ve performance profile cu.
- Pose Action AI mac dinh 3 FPS. Day la tan so du de nhan biet ngoi/dung/gio tay/di chuyen ma giam tai CPU.
- Main preview JPEG chi duoc encode khi co client thuc su yeu cau, giam CPU khi chi mo Classroom.
- API moi: `/api/v1/camera/frame_classroom.jpg`.
- Cache-buster frontend V1.3.1 de Chrome khong dung JS/CSS cu.

## Khong thay doi

- Recognition pipeline va nguong nhan dien ngoai Classroom.
- FaceID enrollment 2 vong.
- Database/FaceID templates.
- YOLO FarFace training tooling.
