# TEST REPORT - CampusFace V1.3.1 Smooth Classroom

## Ket qua

- Python compile: PASS
- JavaScript syntax: PASS
- Existing regression suite: PASS
- V1.3.1 on/off + low-latency contract: PASS
- Tong: **20/20 tests PASS**

## Cac regression da khoa

1. Quan ly lop hoc khong tu dong bat khi chi mo trang.
2. Co nut Bat quan sat/Tat quan sat.
3. Classroom dung `/api/v1/camera/frame_classroom.jpg`, khong dung MJPEG backlog.
4. Preview 10 FPS / 960 px / JPEG 70 mac dinh.
5. Face AI khi Classroom bat gioi han 8 FPS; Recognition ngoai Classroom van dung profile hien co.
6. Pose mac dinh 3 FPS.
7. Classroom start/stop bat/tat performance mode trong CameraService.
8. Cac test FaceID, xoa sinh vien, action AI, deployment, FarFace YOLO van PASS.

## Gioi han test

Moi truong build khong co webcam Windows cua nguoi dung. Do do do tre thuc te can duoc test tren laptop dich. Neu may yeu hon, co the ha `MODULE_CLASSROOM_PREVIEW_FPS` xuong 8 hoac `MODULE_CLASSROOM_PREVIEW_WIDTH` xuong 800 ma khong anh huong do phan giai AI.
