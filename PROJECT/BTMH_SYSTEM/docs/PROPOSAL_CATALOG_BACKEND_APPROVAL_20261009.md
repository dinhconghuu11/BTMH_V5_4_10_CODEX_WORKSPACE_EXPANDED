# Phương án cần phê duyệt — danh mục backend BTMH

Trạng thái: **ĐÃ PHÊ DUYỆT BACKEND TRÊN TEST DB**. Người dùng trả lời “Phê duyệt backend trên test DB” ngày 2026-10-09. Triển khai/kiểm thử code và migration ở môi trường tách biệt; không deploy hoặc migration Production. Phần UI giai đoạn đầu được ghi trong `FINAL_REPORT_ENTERPRISE_UI_20261009.md`.

## 1. Đổi tên camera không restart

Bằng chứng source: `main.camera_configuration_save` luôn gọi `AI_RUNTIME.reserve_camera(device_id)` trước khi lưu. `CameraAIRuntime.reserve_camera` gọi `_retire`; `_signature` serialize toàn bộ context, bao gồm tên camera. Vì vậy chỉ bỏ `reserve_camera` ở route vẫn không đủ: supervisor sẽ nhận signature khác và tạo lại worker. UI của đợt này để tên camera readonly và công khai chưa hỗ trợ đổi tên an toàn.

Phạm vi đề xuất: một luồng lưu metadata tên, giữ nguyên camera_id/source/store/zone/các cờ AI/entrance. Phân quyền dùng `camera.configure` và scope hiện có; validate tên, transaction/audit theo ID; không có secret field trong response. Phải tách chữ ký cấu hình ảnh hưởng xử lý khỏi metadata hiển thị và cập nhật tên cho các owner đang chạy bằng cơ chế đồng bộ được kiểm thử. Track/session và evidence cũ không bị sửa; bản ghi mới dùng tên phù hợp tại thời điểm phát sinh. Đây là thay đổi runtime/pipeline quản lý cấu hình, cần phê duyệt theo yêu cầu master.

Gate: test chứng minh rename không gọi retire/start/source handover; worker/capture identities không đổi; appearance ID, sequence, PAD/FaceID/tracks và history không reset; API scope/secret/audit; fail/rollback không trả save thành công. Sau automated gate vẫn cần nghiệm thu camera thật.

## 2. Cửa hàng: sửa / ngừng hoạt động / lưu trữ

Hiện có GET/POST `/api/v1/stores`, schema stores có ID/code/name/status/timezone. Đề xuất API bổ sung tương thích (không sửa payload API hiện có), scope và `system.manage` như hiện tại. Rename giữ ID, history snapshots giữ tên cũ; không thay timezone dữ liệu lịch sử. Archive phải kiểm tra quan hệ nhân sự, camera, ca và tài khoản; không xóa vĩnh viễn khi có liên kết. Định nghĩa việc tiếp tục ghi nhận camera/attendance ở cửa hàng inactive phải được chốt trước khi triển khai; không suy đoán hoặc tự ngắt camera.

Gate: existing clients vẫn hoạt động, ID/relationships/history nguyên vẹn, cross-store bị chặn trực tiếp API, duplicate/validation/409 rõ ràng và audit. Rollback giao diện/API không xóa dữ liệu.

## 3. Khu vực có ID và CRUD riêng

Hiện `zone_name` là chuỗi của camera, không có zone_id/entity. UI hiện tổng hợp theo `(store_id, zone_name)` và dẫn tới editor hiện có, không giả lập CRUD zone độc lập.

Đề xuất schema additive zone ID và quan hệ hiện tại; trước migration phải có báo cáo dry-run về tên trùng, camera thiếu store, case/whitespace và quan hệ lịch sử. Không tự gộp khu vực chỉ vì tên giống nhau; các store khác nhau có namespace riêng. Không rewrite snapshot history; chuyển camera/store/zone là luồng cấu hình có kiểm tra quyền/quan hệ, không áp dụng như rename thuần metadata. Migration chỉ chạy trên bản sao/test database trước, backup và kế hoạch rollback rõ ràng.

Gate: PostgreSQL test cluster và SQLite contract, migration dry-run/repeatability, scope/audit, ID ổn định, ràng buộc xóa/lưu trữ và history snapshots; cần phê duyệt migration và ảnh hưởng nghiệp vụ trước Production.

## Giới hạn phê duyệt đề nghị
Phê duyệt thực hiện/kiểm thử code backend và migration trên dữ liệu thử nghiệm tách biệt cho ba phạm vi trên. Không bao gồm triển khai khách hàng, chạy migration Production, đổi thresholds/model/PAD, thay cơ chế auth/RBAC hoặc xóa dữ liệu lịch sử. Các thay đổi gây ảnh hưởng khác phải báo cáo lại trước khi làm.
