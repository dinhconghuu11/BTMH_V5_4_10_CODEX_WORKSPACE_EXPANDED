# CHANGELOG V1.2

## UI
- Giu nguyen shell/sidebar/layout cua V1.
- Chi nang cap khu vuc scanner tren trang Dang ky FaceID.
- Them vong quet sinh trac hoc 2 pass, segment progress, depth dots, huong dan di chuyen dau, dem mau 0/14.
- Overlay tiep tuc dung landmark that tu detector, khong dung animation gia de thay AI.

## Quan ly sinh vien
- Tab Hoat dong lop co preview camera live tu CameraService dung chung.
- Overlay bbox/skeleton va thong tin hanh dong hien tai.
- Hien lich su hanh dong cua dung sinh vien dang xem.
- Them API `/api/v1/students/{student_id}/activity-live`.
- Sua lifecycle de chuyen trang khong race start/stop Classroom engine.

## Stability
- Sua scale bbox FaceID -> full camera frame truoc khi Pose tao body ROI.
- Them sample gap cho enrollment de tranh lay nhieu mau gan nhu cung mot frame.
- Nhe dieu kien pose enrollment de phu hop webcam laptop ma van giu 2 pass/14 mau.

## Deployment
- Them `SETUP_AND_START_CAMPUSFACE_WINDOWS.bat`.
- Ho tro runtime da co, bundle offline da prepare, hoac setup tu Python local.
- Du lieu tiep tuc luu o `%LOCALAPPDATA%\CampusFaceV1`, tach khoi thu muc code.
- Portable builder doi ten output thanh `CampusFace-V1.2.1-OFFLINE-PORTABLE.zip`.

## YOLO FarFace
- Training tach rieng trong `.venv-training`.
- Dataset contract 1 class `face` cho face proposal/detection xa.
- Train tu local `training/base_models/yolo26n.pt`, mac dinh imgsz 1280.
- Best model copy ve `models/campusface-face-yolo.pt`.
- SFace van lam identity; YOLO khong train moi sinh vien thanh mot class.
