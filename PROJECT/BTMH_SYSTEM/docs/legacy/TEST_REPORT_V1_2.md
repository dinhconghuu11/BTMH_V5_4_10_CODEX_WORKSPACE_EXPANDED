# TEST REPORT — CampusFace Recognition Module V1.2 Stable Deployable Offline

## Muc tieu kiem thu

V1.2 chi tap trung vao ba thay doi co kiem soat tren nen V1 on dinh:

1. Giu nguyen shell/giao dien tong the, nang cap rieng man quet dang ky FaceID theo kieu quet sinh trac hoc 2 vong.
2. Ho so sinh vien co tab **Hoat dong lop** su dung cung CameraService va AI hanh dong local.
3. Dong goi de trien khai de hon: mot entry point `SETUP_AND_START_CAMPUSFACE_WINDOWS.bat`, du lieu ben vung tach khoi code, training YOLO FarFace tach khoi runtime on dinh.

## Ket qua tu dong

- `tests/run_tests.py`: **16/16 PASS**.
- `python -m compileall module_app scripts tests`: **PASS**.
- `node --check frontend/js/app.js`: **PASS**.
- Camera recovery contract voi backend gia lap: **PASS**.
- Enrollment 2 pass / 14 mau that: **PASS**.
- Xoa sinh vien thu hoi FaceID va state nhan dien/classroom: **PASS**.
- Classroom action geometry/state machine: **PASS**.
- Student profile activity API/UI contract: **PASS**.
- Mapping bbox FaceID tu frame AI resize ve frame camera goc: **PASS**.
- Easy deployment contract: **PASS**.
- Optional YOLO26 FarFace training contract: **PASS**.
- Release-clean guard (khong dong goi DB/key/log/backup/anh dataset/module.env): **PASS**.

## Loi on dinh da sua

Truoc V1.2, FaceID co the nhan dien tren frame da resize trong khi MediaPipe Pose xu ly frame camera goc. Bbox mat neu dung truc tiep se bi lech ROI khi hai do phan giai khac nhau. V1.2 map toa do FaceID ve dung kich thuoc frame goc truoc khi tao body ROI cho Pose.

## Gioi han kiem thu hien tai

Moi truong dong goi nay **khong co camera laptop Windows vat ly**, vi vay khong tuyen bo da kiem thu phan cung that tren may cua nguoi dung. Truoc demo can chay smoke test tren chinh may Windows se trinh dien:

1. Mo/duy tri camera it nhat 10 phut.
2. Dang ky mot nguoi du 2 vong/14 mau.
3. Ra khoi khung hinh va vao lai de xac nhan re-entry.
4. Mo Quan ly sinh vien > Hoat dong lop; kiem tra camera khong bi tranh chap va hanh dong thay doi theo nguoi that.
5. Thu doi do phan giai/camera USB neu co.

## Ket luan

V1.2 dat regression/static contract trong moi truong build. Ban giao demo chi nen goi la **stable candidate** sau khi vuot qua smoke test camera that tren may demo.
