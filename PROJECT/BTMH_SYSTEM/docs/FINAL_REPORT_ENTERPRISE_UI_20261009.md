# BTMH — tái thiết kế UI quản trị, 2026-10-09

**Đã triển khai phần UI an toàn, kiểm thử Node/HTTP và kiểm tra trực quan. HOÀN THÀNH MỘT PHẦN; chưa nghiệm thu thương mại/Production.** CRUD danh mục đầy đủ, đổi tên camera không restart và nghiệm thu thiết bị thật còn cần xử lý riêng. Không deploy, không sửa schema, API/backend, FaceID/PAD, tracking hay dữ liệu khách hàng.

## 1. Phạm vi và kết quả từng chặng

| Chặng | Kết quả source / UI | Kiểm tra / trạng thái |
|---|---|---|
| Audit | Đọc tài liệu bắt buộc, PLANS, source UI/API/schema/RBAC và báo cáo realtime. Ma trận module/capability trong AUDIT_ENTERPRISE_UI_20261009.md | Đã audit các module liên quan; không tuyên bố đã đọc mọi file legacy hoặc chạy mọi thiết bị |
| Design system | Tokens tập trung theo #7B2638 / #571827 / #FAF7F2 / #FFFFFF / #C5A46D; font hệ thống tiếng Việt; section 24–32px, card 20–24px; grid minmax; shared form/table/button/focus | Đã triển khai; visual responsive PASS trong phạm vi dưới đây |
| Sidebar / header | Ba nhóm Vận hành, Nhân sự & báo cáo, Cài đặt hệ thống; bổ sung route ca làm, hiện diện, HR report, khách và danh mục; nhóm camera thu gọn; bỏ trạng thái “đang hoạt động” giả định; mobile focus/Escape/Tab và skip link | Đã triển khai; không mất page IDs; UI guard mirror quyền API hiện có |
| Tổng quan | Bốn KPI: tổng nhân sự, nhân sự xác minh DISTINCT, ca có ghi nhận hợp lệ, sự cố mở. Đối chiếu ca, chart counts, công việc, lượt ghé/store comparison và recent thật | Đã triển khai; không tạo tỷ lệ/vắng bằng phép trừ nhân sự; không video/AI FPS; unknown khác 0 |
| Danh mục | Cài đặt → Danh mục & cấu hình → Cửa hàng / Khu vực / Camera. Store search/create với GET/POST thật; zone list theo `(store_id,zone_name)`; camera search/store filter và editor cũ | Đã triển khai phần API hiện có; rename/archive/delete cửa hàng và zone CRUD độc lập CHƯA HỖ TRỢ |
| Nhân sự | Spacing/form/table theo shared tokens; thao tác Xóa chuyển vào menu ••• có nội dung mở ngay trong hàng để tránh popup bị cắt; giữ search/filters/profile/FaceID/QR | Đã triển khai presentation; modal geometry đã kiểm tra; toàn bộ CRUD/enrollment với người thật chưa nghiệm thu |
| Chấm công & báo cáo | Điều hướng rõ hơn, filters/exports/table giữ API; grid co đúng chiều rộng nội dung, sửa lỗi tràn bộ lọc ở tablet/mobile và lỗi 1366px phát hiện khi phát triển | Đã triển khai; tests JS hiện có và visual PASS; exports nghiệp vụ Production chưa kiểm tra |
| Camera & giám sát | Grid/video owners và route IDs giữ; shared layout/tokens, trạng thái kết nối nghiệp vụ | Regression JS PASS; video WebRTC/Hikvision thật chưa nghiệm thu |
| Nhận diện | Brand light surface theo tokens chung, camera lớn, panel/strip/recent/evidence giữ cấu trúc. Confidence số và thanh % xác minh ẩn; đăng ký hiển thị quality label thay % | Presentation PASS; không suy ra detector/PAD/FaceID chính xác hoặc FPS tăng |
| Giám sát kỹ thuật | Cài đặt có nhóm chẩn đoán/quản trị; metrics chia Tình trạng / AI / Camera-video / Tài nguyên; nhật ký vẫn có guard. Preview camera chỉ khi mở details và có camera.live + system.diagnostics, dùng BTMHMedia native-first | Lifecycle/permission/unknown/secret tests PASS; telemetry/API/logs không xóa |
| Tích hợp | Node, real isolated HTTP, full tests_v54 trước/sau, syntax, topology, Chrome | Kết quả cụ thể bên dưới; Python còn FAIL nền, không đủ điều kiện release |
| Bàn giao | Snapshot ZIP/checksum, audit/ExecPlan/report, ảnh trước/sau, XML đối chiếu, phương án backend cần phê duyệt | HOÀN THÀNH MỘT PHẦN |

## 2. Source đã thay đổi

Sản phẩm:
- `frontend/index.html`: navigation, KPI/tasks/catalog tabs, settings sections, readonly camera name, trạng thái/ẩn score, cache version.
- `frontend/css/btmh_design_v550.css`: tokens, spacing/grid, controls/table/modal/focus/row menu, bỏ gradient topbar.
- `frontend/css/btmh_management.css`: KPI grid, task list, chart counts responsive.
- `frontend/css/btmh_recognition_console.css`: bỏ tokens màu riêng, dùng tokens chung; spacing panel giữ media geometry.
- `frontend/css/btmh_catalogs.css` (mới): tab/table/search/form danh mục.
- `frontend/js/app.js`: route labels/permission mirror, catalogue delegation, native preview opt-in, secondary HR actions, registry refresh sau thêm camera và quality label.
- `frontend/js/btmh_customer_v541.js`: nhóm nav theo quyền, mobile keyboard/focus.
- `frontend/js/btmh_management.js`: KPI allowlist/unknown, task/chart counts, giữ scoped cancellable polling.
- `frontend/js/btmh_catalogs.js` (mới): safe catalog views, GET/POST stores, registry-derived zones, tabs, validation/ack/abort/actor guards.
- `frontend/js/btmh_camera_configuration.js`: search/store filter, không fetch/mount editor khi camera tab ẩn, giữ draft và owner.
- `frontend/js/btmh_diagnostics_v550.js`: nhóm hiển thị telemetry, giữ endpoint/passive read/polling/permission lifecycle.

Kiểm thử: `tests_browser/catalogs.test.cjs`, `visual_enterprise_ui.cjs` (mới); cập nhật `camera_configuration.test.cjs`, `customer_diagnostics_ui.test.cjs`, `diagnostics_lifecycle.test.cjs`, `management_dashboard.test.cjs`, `smoke_ui_preview.py`. Fixture camera có thêm chuẩn DOM `select.options` phục vụ filter mới; không bỏ assertion bảo mật/lifecycle.

Tài liệu: ExecPlan, audit, report này, `PROPOSAL_CATALOG_BACKEND_APPROVAL_20261009.md`, evidence dưới `docs/checkpoints/enterprise-ui-20261009/`. `docs/VERIFY_RELEASE_RESULTS_V550.json` là output verifier, giữ bản trước tại checkpoint. Inventory SHA/source: `source-changes.json`.

## 3. Dữ liệu và bảo toàn hệ thống

Summary backend hiện có cung cấp employees.total, nhân sự DISTINCT đã RECOGNIZED + anti_spoof_passed, ca theo effective assignments, incidents biết scope và lượt IN được xác minh theo policy. UI không dùng appearance/bounding box làm khách duy nhất hoặc chấm công. Ca và người có đơn vị khác nhau; late/absent chỉ hiển thị khi `attendance.configured===true`. Không có ca/field/numeric hợp lệ → “—”, không suy ra 0. Không có pending-approval KPI vì summary chưa cung cấp.

Stores đọc theo dashboard.view, create theo system.manage; zone/camera theo camera.live và camera.configure của API cũ. Mọi permission backend, MFA/Owner bootstrap/session và historical store/zone/name snapshots giữ nguyên. Không copy runtime credentials/models/data vào source; không có mock nhận diện/chấm công trong sản phẩm. Static layout fixtures và dữ liệu HTTP test chỉ trong QA tách biệt.

**Phát hiện quan trọng:** `camera_configuration_save` gọi reserve_camera → _retire cho mọi save; `_signature` chứa toàn bộ context, cả tên. Vì vậy rename hiện tại có thể restart AI dù camera_id/source không đổi. Đã để tên readonly trong UI; chưa tạo rename API hoặc sửa signature/pipeline để vượt qua yêu cầu phê duyệt. Các cờ AI/store/zone/entrance vẫn dùng luồng cấu hình đã tồn tại. Không quảng bá rename không restart là đã hoàn thành.

## 4. Kiểm thử thực chạy

| Kiểm tra | Kết quả |
|---|---|
| Node baseline toàn bộ | 393 PASS / 0 FAIL |
| Node cuối toàn bộ | **407 PASS / 0 FAIL / 0 skip**; gồm media/auth/evidence/enrollment/lifecycle cũ, catalogue owner/save/scope-derived views, truthful KPI và native preview opt-in |
| Python baseline `pytest -q tests_v54` | 618 tests: **603 PASS, 15 FAIL**, 0 skip |
| Python sau `pytest -q tests_v54` | 618 tests: **603 PASS, 15 FAIL**, 0 skip; XML đối chiếu **0 FAIL mới**, cùng 15 node IDs |
| Real HTTP preview | **8 PASS**; Uvicorn loopback + SQLite profile mới; 3 trang/39 assets, real owner login/logout, stores POST/list/duplicate400/anonymous401/Manager403, dashboard ngoài scope403, QR guard và hardware fail-closed |
| JavaScript syntax | Tất cả file frontend/js hiện tại đã `node --check` thành công; app/catalog checked lại sau native-preview sửa cuối |
| Python compile | `tests_browser/smoke_ui_preview.py` PASS; không sửa Python sản phẩm |
| HTML topology | 691 IDs, 0 ID mất/duplicate, 0 page lồng sai, 0 nav thiếu route, một main landmark |
| Chrome static visual | **105 observations PASS**: 17 trang × 5 viewport + 4 form/modal mở × 5 viewport; 0 HTTP API requests, 0 browser JS exception |
| `VERIFY_RELEASE.py` | Đang ghi kết quả cuối; xem `release-after.txt` và `docs/VERIFY_RELEASE_RESULTS_V550.json`. Không xem là PASS trước khi tool kết thúc |

15 FAIL nền ở camera/fleet/RTSP/native startup/WS và static QR permission-map contract. Baseline XML cho thấy các lỗi camera chủ yếu `sqlite3.OperationalError` thiếu camera_devices/ai_camera_runtime tables trong fixture; mapping test QR có route do middleware riêng bảo vệ không nằm trong bảng static test. Chưa sửa fixture/backend/security trong task UI; không kết luận các FAIL này vô hại cho Production. Danh sách đầy đủ: `python-comparison.json`; raw source test logs không phải camera/customer logs.

Môi trường: Python hệ thống thiếu pytest; QA venv có dependencies hiện có nhưng sandbox không đọc đủ package. Dùng auto-review cho phép cùng venv, không cài/sửa package. Node child-process và Chrome inspection cần auto-review vì sandbox EPERM. Không có rejection auto-review; không đổi Production policy.

## 5. Kiểm tra trực quan và giới hạn

Chrome headless thực, profile mới, static server loopback tạm. Viewports 1920×1080,1440×900,1366×768,768×1024,390×844. 17 pages: dashboard/students/history/ops-center/system/recognition/live-grid/playback/register/work-shifts/hr-report/operations/incidents/visitors/admin-security/camera-control/live-monitor. Thêm store form, employee modal, camera settings details, report filters mở. Đã xem ảnh dashboard desktop, recognition desktop, nhân sự mobile và hai form mobile. Check tự động: page/control overflow, visibility guards, sidebar không đè main desktop, camera tab keyboard, mobile menu focus/Escape. Thanh cuộn ngang chủ ý của table/nhóm nhân sự/strip camera được giữ để truy cập bằng bàn phím.

Baseline source snapshot: 85 observations; thấy bộ lọc history tràn ở tablet/mobile. Sau sửa: 105 observations PASS. Trong vòng phát triển cũng tái hiện overflow history1366 do implicit grid min-content; sửa grid columns minmax(0,1fr), rồi chạy lại. Lần chụp đầu auth shell bị ẩn trong harness; kết quả đó **không dùng nghiệm thu**, được chuyển vào `obsolete-qa-attempts/`. Ảnh baseline hợp lệ được chụp lại từ ZIP source-before, không dùng source sau sửa giả làm baseline.

Ảnh tham khảo (đều QA, không Production):
- [Tổng quan trước](checkpoints/enterprise-ui-20261009/visual/before/dashboard-1920.png) / [sau](checkpoints/enterprise-ui-20261009/visual/after/dashboard-1920.png).
- [Nhận diện trước](checkpoints/enterprise-ui-20261009/visual/before/recognition-1440.png) / [sau](checkpoints/enterprise-ui-20261009/visual/after/recognition-1440.png).
- [Form nhân sự mobile](checkpoints/enterprise-ui-20261009/visual/after/form-employee-390.png), [Danh mục mobile](checkpoints/enterprise-ui-20261009/visual/after/ops-center-390.png).

Chưa kiểm tra đủ screen reader/WCAG 2.2 AA, toàn bộ modal focus traps/CRUD bằng browser với database thật, tải trọng danh sách lớn, tất cả role/store combinations và exports thực. Hardware/video/PAD false reject/FaceID accuracy/HTTP face evidence trên Production vẫn **CHƯA NGHIỆM THU**, theo báo cáo realtime đang mở; UI mới không giải quyết thay cho vấn đề inference.

## 6. Rủi ro, rollback và bước tiếp theo

Rủi ro chính: CSS legacy vẫn còn trong bundle; automated/static visual không chứng minh mọi dữ liệu dài/role/modal tổ hợp. Native preview hệ thống mới cần kiểm tra gateway thật khi mở details; closed details không tạo demand. Camera metadata rename/store archive/zone ID CRUD và chấm công Production chưa hoàn thành. Full Python/release gate còn FAIL, không tạo installer hoặc deploy.

Git CLI/.git không khả dụng; không reset/checkout. ZIP `source-before.zip` chứa 114 frontend/test source files, SHA256 **d1574240eb4619d74365f89393af35f312ffc0b26cc1df5842792c3c21bfb70a**. Khi rollback, so diff/hash riêng các file trong `source-changes.json` rồi khôi phục từ ZIP, giữ sửa mới của người dùng. Các file thêm mới được inventory để gỡ riêng nếu cần; không xóa database/profile khách hàng. Có thể phục vụ source mới bằng server workspace hiện tại và Ctrl+F5; Codex không restart/deploy Production.

Bước tiếp theo cần phê duyệt được mô tả cụ thể trong [phương án backend](PROPOSAL_CATALOG_BACKEND_APPROVAL_20261009.md): rename camera giữ worker/track; store sửa/lưu trữ với ràng buộc quan hệ; zone entity/migration additive trên test DB. Không bao gồm deploy/migration Production hoặc đổi model/PAD/threshold/security. Tiếp đó xử lý 15 FAIL nền và nghiệm thu Windows/Hikvision/PostgreSQL thật.
