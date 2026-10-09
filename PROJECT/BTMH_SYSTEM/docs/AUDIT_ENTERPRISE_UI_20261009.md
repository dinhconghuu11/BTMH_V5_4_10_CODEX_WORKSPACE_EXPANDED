# Audit UI/API BTMH — 2026-10-09

Audit source có liên quan tới toàn bộ module UI đang đăng ký; không khẳng định đã chạy thiết bị thật hoặc đọc mọi file legacy. Không có Git CLI/.git: không xác định được uncommitted diff; snapshot nguồn hiện tại bảo vệ công việc có sẵn.

| Module / mục đích | Hiện có | Frontend | API / backend đã kiểm tra | Quyền | Vấn đề / cải thiện | Rủi ro / quyết định |
|---|---|---|---|---|---|---|
| Tổng quan / điều hành | Nhân sự, ca, lượt ghé, sự cố, recent | index.html, btmh_management.js/css | GET /api/v1/dashboard/summary; visit_reports.py, shift_attendance.py | dashboard.view + scoped_store_ids | Chưa có total nhân sự trên UI; nhận diện không đồng nghĩa chấm công; bổ sung KPI truthful và công việc theo ca | Thấp; sửa presentation, giữ query |
| Nhận diện & chấm công | Single view, strip registry, tracks, #NNNN, PAD, evidence/recent | app.js, recognition_slots, recent_recognition, recognition_console | recognition/cameras,recent; camera metadata/evidence; ai_camera_runtime | camera.live, evidence.view, camera/store scope | Confidence số còn trên chi tiết; giữ trạng thái xác minh, bỏ score khỏi nghiệp vụ | Cao nếu đổi thuật toán; chỉ sửa presentation |
| Camera & giám sát | Grid 1/4/9/16, main fullscreen, playback, clips | btmh_v4.js, media_v5410.js | cameras/fleet/v4, media WHEP, playback/recording routes | camera.live/playback,video.clip | Menu/video đã hoạt động; chuẩn hóa tên/trạng thái và spacing | Giữ owners/transport/handover |
| Nhân sự / hồ sơ | Search, filter, CRUD, face enrollment và QR review | app.js, qr_enrollment_admin.js, index.html | students, enrollment/QR; registry.py, qr_enrollment_routes.py | employee.view/manage/enroll và scope | Nhiều tầng card/nút; spacing/form/table thống nhất; không thay phê duyệt | Vừa; sửa layout |
| Ca làm | Thiết lập ca, phân công effective history | app.js | work-shifts, shift assignments; platform_v5.py, shift_attendance.py | attendance.view/manage | Route có nhưng khó tìm ở sidebar | Thấp; thêm đường dẫn hiện có |
| Chấm công & báo cáo | Recognition/HR/visits, date/store/employee filters, exports | btmh_demo_reports.js,app.js | history/HR/report options, hr-report; hr_reporting.py | history.view,attendance.view,hr.report và scope | Tên nhóm cần rõ; bảng/filters cần thoáng | Thấp; giữ semantics |
| Danh mục cửa hàng | GET danh sách + POST tạo, audit | Hiện select trong enrollment/RBAC/camera | GET/POST /api/v1/stores; platform_v5.py | dashboard.view để đọc, system.manage để tạo | Chưa có màn hình; thêm bảng/search/create dùng API hiện có | Không thêm rename/archive/delete API trong task |
| Khu vực | zone_name chuỗi trên camera | CameraConfiguration editor | camera_appearances.py + devices/id/configuration | camera.live đọc, camera.configure sửa | Chưa có entity/zone_id; tổng hợp read-only và đi tới editor camera | CRUD riêng cần thiết kế schema/API và phê duyệt |
| Camera registry / cấu hình | Gán store/zone, AI/attendance/entrance, GET/PUT audit | btmh_camera_configuration.js/css | GET/PUT devices/id/configuration; reserve_camera + reconcile | camera.configure, enforce_store_scope | Nằm riêng ops-center, thiếu search/filter | Chuyển vị trí điều hướng, giữ route/IDs/source/editor; không tự chuyển lịch sử |
| Cài đặt / chẩn đoán | Health, allowlisted performance, logs, camera settings, backups, edge, mobile | app.js, diagnostics_v550.js | system/diagnostics/performance + health/logs; performance_diagnostics_v550.py | system.health,system.diagnostics,system.manage và role guards | Màn hình dài trộn chức năng; phân nhóm rõ, tránh tự mở JPEG preview, 5 nhóm telemetry | Không xóa API/logs hoặc mở quyền |
| Tài khoản/bảo mật | Owner bootstrap, sessions/MFA/SMS, profile, RBAC | account_profile.js, app.js, sms_v542.js | auth.py, security_hardening_v54.py, account_service.py | Role/permission backend hiện có | Giữ UI auth vừa được sửa và bảo vệ hoạt động | Không thay cơ chế bảo mật |
| Sự cố / bằng chứng | Create incident, evidence/clip protection | app.js,index.html | incident/evidence routes, production_ops.py | incident.view/manage,evidence.view | Giữ cảnh báo nghiệp vụ; unify table/forms | Thấp presentation; không xóa evidence |

## KPI và capability thực tế
`query_management_summary` trả `employees.total`, nhân viên DISTINCT với recognition RECOGNIZED + anti_spoof_passed, ca đã phân công và các IN lượt ghé theo timezone/snapshot. Vì chưa có số người chưa chấm công theo mẫu số nhân sự hợp lệ, không dùng total trừ recognition để kết luận vắng. Vắng/late chỉ dựa DTO ca; số ca != số người. Visit appearance != khách duy nhất. Không tạo KPI attendance rate hoặc approval count khi summary chưa cung cấp.

Store DELETE/PUT và zone CRUD không tồn tại tại main.py. Camera metadata rename đi qua full configuration PUT/reserve/reconcile hiện có; task không bảo đảm mọi rename backend không có handover trong mọi runtime. Không phát minh endpoint hoặc dùng legacy generic update thay editor an toàn. PostgreSQL/FaceID/PAD/RTSP cấu hình giữ nguyên.

## Baseline
Node 393 PASS. Python/release đang đo; sẽ ghi FAIL sẵn có cụ thể vào báo cáo cuối. Visual/layout fixtures chỉ để kiểm tra bố cục, không chứng minh CRUD Production hoặc nhận diện người thật.
