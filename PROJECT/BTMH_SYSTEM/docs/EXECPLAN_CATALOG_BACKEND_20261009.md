# ExecPlan — backend danh mục được phê duyệt trên test DB

## Mục tiêu / phê duyệt
Ngày 2026-10-09 người dùng phê duyệt phương án `PROPOSAL_CATALOG_BACKEND_APPROVAL_20261009.md`: đổi tên camera giữ worker/capture/track, sửa/lưu trữ cửa hàng, CRUD khu vực có ID và migration additive trên test DB. UI phải gọi API thật, phản ánh lỗi/ack và scope.

## Kiến trúc / vấn đề
Route cấu hình luôn reserve/retire; runtime serialize toàn context và `configure_ai_pipeline` reset trạng thái khi tên thay đổi. Stores chỉ có GET/POST. Zone hiện là chuỗi camera. Tên trong history là snapshot. PostgreSQL là database sản phẩm, SQLite dùng kiểm thử.

## Phạm vi file
`module_app/{main,camera,ai_camera_runtime,demo_context}.py`; module `catalog_backend.py`; script migration opt-in; `frontend/{index.html,js/btmh_catalogs.js,js/btmh_camera_configuration.js,css/btmh_catalogs.css}`; tests và báo cáo.

## Quyết định nghiệp vụ / bảo vệ
Metadata tên không đổi signature hành vi. Cập nhật metadata giữ lock runtime và lock AI giữa hai frame; không gọi configure/reset engine. Snapshot đang xử lý/history giữ nguyên. Cửa hàng inactive/archive chỉ khi không còn quan hệ camera/nhân sự/ca/tài khoản/khu vực hoạt động; không tự ngắt camera. Không cho thay timezone cửa hàng đã có quan hệ hoặc history. Không xóa cửa hàng. Khu vực đổi tên/lưu trữ/xóa chỉ khi không gắn camera; khu vực đã có history không xóa. Chuyển khu vực camera vẫn dùng handover cấu hình hiện có. Không tự gộp vùng cũ: migration mặc định chỉ tạo bảng; backfill cần mapping camera ID rõ ràng được chọn từ dry-run.

## Migration / rollback
Migration không được gọi khi import hoặc startup. Dry-run chỉ đọc, báo nhóm tên chính xác theo store, camera không có/mơ hồ store, khác case/whitespace. Apply yêu cầu khai báo test database/profile rõ ràng; schema additive, transaction, idempotent, PostgreSQL advisory lock/SQLite BEGIN IMMEDIATE. Lịch sử không sửa. Backup file nguồn trước nằm `docs/checkpoints/catalog-backend-20261009/source-before/` cùng SHA256. Rollback source riêng file, giữ bảng/ID; không drop database hoặc xóa lịch sử. Production cần phê duyệt riêng.

## Security/privacy
Giữ permission camera.configure/system.manage và scope backend; map endpoint mới trực tiếp, kiểm tra scope trong transaction. Audit cùng transaction với mutation mới. Không thêm secret/source vào payload. Tên validate và render textContent. API lỗi dùng mã cố định, không SQL/credentials. Không mở camera thật trong test.

## Test plan / tiêu chí
Narrow tests: rename primary/aux giữ identity, source epoch, appearance/sequence/PAD/track; thay hành vi vẫn retire; lỗi DB/audit rollback; scope trực tiếp API. Stores dependency409/validation/ID/history. Zones migration dry-run không mutate, mapping rõ ràng, repeatable, constraints và assignment khác store. HTTP auth/RBAC trên SQLite riêng. PostgreSQL test cluster nếu binary cục bộ có sẵn, không dùng customer database. Node lifecycle/ack/API; syntax compile; full tests_v54 và release đối chiếu 15 FAIL nền. Cập nhật ảnh UI và kết quả thực chạy.

## Checkpoints
- [x] Nhận phê duyệt, đọc source, snapshot các file trước backend.
- [ ] Metadata runtime + route rename và kiểm thử giữ trạng thái.
- [ ] Store metadata/status với transaction/audit/dependency guard.
- [ ] Zone entity, migration opt-in, assignment tương thích.
- [ ] UI kết nối APIs, narrow regression/HTTP.
- [ ] PostgreSQL nếu khả dụng, full regression, báo cáo bằng chứng/giới hạn.

## Bằng chứng
Đang triển khai; chưa có kết quả backend để đánh dấu PASS.
