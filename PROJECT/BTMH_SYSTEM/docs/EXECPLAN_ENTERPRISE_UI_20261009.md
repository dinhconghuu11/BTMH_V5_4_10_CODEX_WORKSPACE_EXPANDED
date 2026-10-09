# ExecPlan — UI quản trị BTMH, 2026-10-09

## Mục tiêu và tiêu chí người dùng
Chuẩn hóa giao diện đỏ rượu vang / kem / trắng / vàng đồng, spacing 24–32px, điều hướng theo nghiệp vụ. Tổng quan chỉ dùng dữ liệu summary thật và phân biệt nhận diện hợp lệ với chấm công theo ca. Cài đặt dẫn tới Danh mục (Cửa hàng / Khu vực / Camera) và Giám sát kỹ thuật. Các luồng nhân sự, báo cáo, camera và xác minh giữ API/ID hiện có; không có nút CRUD giả.

## Kiến trúc và vấn đề quan sát
Frontend HTML + JavaScript thuần, CSS bundle lịch sử và presentation tokens `btmh_design_v550.css`; FastAPI, PostgreSQL sản phẩm, SQLite kiểm thử; media gateway và AI độc lập. Tổng quan hiện có `/dashboard/summary`, bounded polling; camera có editor với scope/audit và background owner. Sidebar bỏ sót route ca làm/báo cáo/danh mục. Cài đặt là màn hình dài trộn tài nguyên, nhật ký, sao lưu và camera preview JPEG. Nhận diện còn hiển thị confidence số. API cửa hàng có GET/POST, không có rename/archive/delete. Khu vực là chuỗi `zone_name` của registry, chưa có danh mục ID riêng.

## File/phạm vi
`frontend/index.html`, `frontend/css/btmh_design_v550.css`, `frontend/css/btmh_management.css`, `frontend/css/btmh_recognition_console.css`, `frontend/js/app.js`, `frontend/js/btmh_customer_v541.js`, `frontend/js/btmh_management.js`, `frontend/js/btmh_camera_configuration.js`, `frontend/js/btmh_diagnostics_v550.js`; thêm presentation danh mục, test UI/Node và tài liệu. Backend/schema/security/model policy không sửa trong giai đoạn an toàn.

## Vùng bảo vệ và giới hạn
Giữ auth/MFA/bootstrap, permission/store scope backend, registry persistence, handover, media/overlay geometry, background AI/recording, FaceID/PAD thresholds, lịch sử/evidence và ca làm. Không deploy, không reset data, không đổi camera Production. Store rename/archive/delete, zone entity CRUD và thay đổi quan hệ/historical scope cần phương án riêng/phê duyệt nếu API/schema hiện tại không hỗ trợ. Không suy ra camera thật đạt nghiệm thu từ test UI.

## Rollback
Không có Git CLI hoặc `.git` tại workspace/canonical root. Trước sửa lưu ZIP frontend/test nguồn và SHA256 dưới `docs/checkpoints/enterprise-ui-20261009/`. Khôi phục riêng file của task từ ZIP sau khi kiểm tra diff/hash; không ghi đè sửa mới của người dùng, không xóa database. File mới có inventory riêng, không recursive delete. Static cache version thay đổi theo task.

## Security/privacy
Chỉ gọi endpoint đã kiểm tra. Không đọc/resend nguồn RTSP trong danh mục. Render tên qua textContent, lọc nguồn/credentials trong view dữ liệu. Mỗi page/tab request có abort + generation và guard auth/permission. Tab ẩn không được mở media owner hoặc fetch chẩn đoán. Không log cookie/token/password. Test dùng SQLite/profile và Chrome riêng, không kết nối Production 8100.

## Baseline và kế hoạch test
Node baseline: 393 PASS (2026-10-09, runner ngoài sandbox vì child-process EPERM). Python hệ thống thiếu pytest; test venv bị sandbox hạn chế quyền đọc dependency; chạy cùng venv với auto-review, SQLite tạm độc lập. Baseline tests_v54 đang chạy, có FAIL trước thay đổi; ghi chi tiết sau khi hoàn tất. Không cài thư viện hoặc sửa dependencies. Chạy narrow Node UI/lifecycle rồi full Node, Python tests_v54, VERIFY_RELEASE.py; syntax JS. Visual QA Chrome hiện có: 1920×1080,1440×900,1366×768,768×1024,390×844; ghi rõ static layout với dữ liệu rỗng khác với real HTTP/RBAC hoặc hardware.

## Checkpoints
- [x] Đọc 5 tài liệu bắt buộc, PLANS, báo cáo realtime và source frontend/API/schema liên quan.
- [x] Audit module và capability/API thực tế; xác định Git không khả dụng.
- [ ] Baseline Python/release + snapshot nguồn và ảnh trước.
- [ ] Design tokens/layout/shared controls; sidebar nghiệp vụ và focus bàn phím.
- [ ] Tổng quan KPI truthful + công việc cần xử lý, giữ scope/polling.
- [ ] Danh mục ba tab dùng GET/POST stores và editor camera hiện có; khu vực từ registry.
- [ ] Nhân sự/báo cáo/video/nhận diện: spacing, trạng thái, bỏ confidence/debug trình bày không cần thiết.
- [ ] Cài đặt nhóm chức năng/chẩn đoán; giữ telemetry và quyền.
- [ ] Narrow/full regression, real HTTP smoke, visual responsive trước/sau.
- [ ] Báo cáo từng giai đoạn, inventory, rủi ro, nghiệm thu còn thiếu và rollback.

## Bằng chứng nghiệm thu
Sẽ cập nhật kết quả thực chạy và paths ảnh/JSON. Chỉ đánh dấu triển khai/kiểm thử tương ứng; commercial/hardware acceptance và CRUD chưa có API vẫn chưa hoàn thành.
