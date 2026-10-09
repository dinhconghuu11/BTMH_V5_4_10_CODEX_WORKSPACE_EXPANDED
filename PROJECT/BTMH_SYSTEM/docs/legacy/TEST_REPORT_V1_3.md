# TEST REPORT - CampusFace Recognition Module V1.3 Stable Clean Fix

## Pham vi sua

V1.3 chi sua nhung phan dang gay regression trong V1.2.1, khong viet lai pipeline Nhan dien dang hoat dong tot.

### 1. Classroom blank-page regression

Da loai bo loi JavaScript `renderClassroomRoster is not defined` va go cac CSS legacy dang `display:none!important` cho `#page-classroom`.

Trang Classroom duoc rut gon ve scope on dinh:
- shared static camera preview;
- FaceID track;
- local Pose;
- ngoi / dung / gio tay / di chuyen;
- overlay;
- current tracks;
- action event log.

### 2. Enrollment UX

Da doi tu 14 pose bat buoc sang hai vong xoay tu nhien.
Moi vong AI tu thu coverage center / left / right / up / down theo bat ky thu tu nao.
Mot vong co the ket thuc voi 4 sector phan bo tot (bat buoc co left + right + center + vertical) sau thoi gian chuyen dong toi thieu, hoac du 5 sector.
Tong template thuong 8-10 embedding.

### 3. Recognition

DOM/pipeline Nhan dien duoc giu nguyen va regression test van PASS.

## Ket qua test

- Python compile: PASS
- JavaScript syntax (`node --check`): PASS
- Existing regression suite + V1.3 regressions: 19/19 PASS
- Classroom action geometry/state machine: PASS
- Classroom FaceID->full-frame ROI mapping: PASS
- Navigation/page target contract: PASS
- No `renderClassroomRoster` reference: PASS
- Classroom active CSS visibility contract: PASS
- Two-circle enrollment contract: PASS
- YOLO FarFace training contract: PASS
- Release clean guard: PASS before packaging

## Server smoke test

Server khoi dong tren runtime tam va cac endpoint sau tra HTTP 200:
- `/api/v1/health`
- `/api/v1/students`
- `/api/v1/classroom/status`
- `/api/v1/classroom/latest`
- `/api/v1/module/contract`
- `POST /api/v1/classroom/start`
- `POST /api/v1/classroom/stop`

Version tra ve: `1.3.0-stable-cleanfix`.

## Gioi han kiem thu

Moi truong build khong co chinh webcam Windows cua may demo. Vi vay truoc khi demo khach hang van can smoke test 10-15 phut tren laptop that: dang ky 1 nguoi, nhan dien ra/vao, vao Quan ly lop hoc, thu ngoi/dung/gio tay va theo doi camera reconnect.
