# BTMH demo production-lite — audit trước implementation

Ngày: 2026-10-08. Nguồn yêu cầu: MASTER TASK — BTMH DEMO PRODUCTION-LITE do người dùng đính kèm.

## Checkpoint và phạm vi

Đã đọc AGENTS.md, năm tài liệu trong `00_START_HERE`, PRODUCT.md, DESIGN.md và `.agent/PLANS.md`. Tiếp tục canonical source `PROJECT/BTMH_SYSTEM/`; không reset, clean, rollback hoặc discard. Audit đọc schema/service/API/frontend trong source, không mở database triển khai hoặc dữ liệu khách hàng. Chưa chứng nhận schema đã áp dụng trên PostgreSQL thực tế.

Trong checkpoint này chỉ thêm báo cáo này; chưa sửa product code hoặc thực hiện migration. Login, account/logout, development launcher, media architecture, FaceID/PAD, registry, attendance, RBAC và recorder được giữ nguyên.

`git status --short` không chạy được vì Git không có trong PATH. Các vị trí Git phổ biến đã kiểm tra không có executable; không thấy `.git` tại workspace, `PROJECT`, canonical source hoặc các thư mục cha đã kiểm tra. Không có working-tree diff đáng tin cậy để kết luận danh sách thay đổi Git. Đối chiếu checkpoint UI hiện có bằng source và `docs/UI_RESUME_QA_20261007.md`.

## Source đã có và khoảng trống

| Phần | Đã có | Thiếu hoặc có giới hạn |
| --- | --- | --- |
| Camera identity/store/zone | `camera_devices.id` là PK, tên có thể đổi; `zone_name` là text. Có `stores`, `employee_store_assignments`, `camera_store_assignments`. | Assignment camera–store chưa được nối CRUD/runtime. Payload camera chưa có store hoặc cấu hình AI persisted. Không cần tạo lại store model hoặc thay camera ID để bắt đầu. |
| AI backend | Một CAMERA global chạy capture/AI từ startup, độc lập browser. Các lane PAD/FaceID có pending batch giới hạn. | API công bố `SINGLE_ACTIVE_COMPAT`, `simultaneous_ai_workers=False`. Auxiliary FleetWorker chỉ phục vụ JPEG/reader lease; không thực hiện recognition. Chưa có admission/supervisor tối đa bốn camera AI, trạng thái capacity hoặc per-camera pipeline độc lập browser. |
| Recognition UI | Một preview recognition, lớp canvas và metadata WebSocket riêng video; scaling contain và mirror đã có. | Chưa có bốn slot linh hoạt. Metadata hiện lấy CAMERA global, không gắn camera ID của từng slot. Bounding-box issue chưa tái hiện bằng camera thật; chưa kết luận root cause hoặc fix. Resize redraw riêng chưa thấy trong media layer. |
| History attribution | Recognition events có ID, thời gian UTC, identity/PAD/detail; dedup có sẵn. | `camera_source` là nhãn hiển thị mutable, chưa có camera ID/store/zone snapshot. Endpoint history chỉ nhận limit; frontend lọc tập tối đa 1.200 events đã tải, chưa có server-side date/store/zone/camera filters. |
| Attendance | Có check-in ledger first/last, presence IN/OUT, ca làm, gán ca, workdays/grace/ngày hiệu lực và corrections có audit. | Ba mô hình chưa thống nhất checkout chấm công. Gán ca ghi đè một dòng; báo cáo không xét ngày hiệu lực đầy đủ. Default/seed 08:00–17:30 không chứng minh lịch của khách hàng. ABSENT có thể được tính khi ngày/ca chưa kết thúc. Không được gọi last_seen−first_seen là giờ làm. |
| Customer traffic | Có session UNKNOWN track, event dedup, Virtual Gate crossing, daily aggregates hiện có. Không đếm trực tiếp từng detection frame. | Session quan sát không phải lượt IN. Reopen TRACK_LOST cùng camera trong 8 giây chưa kiểm tra cùng người/vị trí; không có anonymous cross-camera visit dedup. Virtual Gate chưa tạo visitor visit lifecycle; hourly UI hiện đếm events, không phải arrivals. Có nguy cơ ACTIVE tồn dư từ source, chưa tái hiện runtime. |
| Auth/RBAC | Admin provisioning có API/backend role guard; Owner tương ứng SUPER_ADMIN; account/logout UI hiện có. Public registration mặc định bị chặn. Có account profile store_id và permission nghiệp vụ. | Menu chưa có hai action self-profile/change-password riêng. Form create hiện có username/display_name/role/password, chưa confirm và các field profile/store được nối provisioning. Registration vẫn có env opt-in. Store scope chưa được enforce đầy đủ trên các report hiện có. |
| Customer UI | Debug block transport và HUD kỹ thuật trên video đã được bỏ/ẩn; brand auth/account đã có. | `renderMediaPlayback` vẫn nối transport/fallback vào badge/title ngoài HUD. Trang recognition còn latency kỹ thuật, tiêu đề camera cố định. Cần xử lý đúng phase UI, giữ recognition overlay và metrics có quyền. |

## Bằng chứng source chính

- Camera schema/update: `module_app/production_ops.py:125`, `:874`; stores/assignments/shifts: `module_app/platform_v5.py:18`, `:34`, `:40`, `:54`.
- Camera pipeline singleton: `module_app/camera.py:945`, `:1528`; startup: `module_app/main.py:925`; multi-camera compatibility response: `module_app/main.py:3466`; auxiliary JPEG worker: `module_app/camera_fleet_v4.py:189`.
- Event schema: `module_app/db.py:186`; event camera display label: `module_app/camera.py:291`; history endpoint: `module_app/main.py:1548`; frontend history/hourly aggregation: `frontend/js/app.js:1624`, `:1647`, `:1771`.
- Attendance ledger: `module_app/production_ops.py:436`, `:465`; presence and gate OUT: `module_app/office_engine.py:355`, `:376`, `:588`; report assignments/default/absence: `module_app/hr_reporting.py:18`, `:206`, `:315`, `:339`; shift assignment overwrite: `module_app/platform_v5.py:303`.
- Visitor semantics/reopen: `module_app/visitor.py:128`, `:153`; unknown-track sessions: `module_app/walkby.py:975`, `:1028`; gate crossing/presence: `module_app/office_engine.py:532`, `:571`, `:584`; visitor aggregate: `module_app/main.py:3733`.
- Auth provisioning/default registration guard: `module_app/main.py:2582`, `:2614`, `:3054`; profile store metadata: `module_app/auth.py:666`; permission check: `module_app/auth.py:1271`.
- Recognition markup/mount/metadata/drawing: `frontend/index.html:351`; `frontend/js/app.js:657`, `:699`; `frontend/js/btmh_media_v5410.js:341`, `:350`; metadata endpoint/payload: `module_app/main.py:2088`, `:2327`.

## Phạm vi đề xuất để người dùng xác nhận

1. **Migration bổ sung tối thiểu:** tận dụng stores/camera_store_assignments và camera_devices.id; bảo đảm mỗi camera thuộc đúng một cửa hàng; giữ zone_name nếu đủ cho demo; thêm attribution ổn định camera/store/zone cho event và persisted AI configuration cần thiết. Store scope được backend enforce theo policy đã chốt. Không tự gán cửa hàng cho dữ liệu cũ; lịch sử thiếu nguồn gốc hiển thị chưa xác định. Không viết lại PostgreSQL core, không dùng display name làm khóa. Chưa áp dụng migration; sau câu trả lời cần ExecPlan và mô tả migration cụ thể trước implementation.
2. **Attendance demo:** chọn first valid recognition + lần ghi nhận cuối, tạm không KPI ca; hoặc hoàn thiện báo cáo theo ca được gán và ngày hiệu lực. Nếu chọn ca, cần policy thời điểm chốt Vắng và ca qua đêm nếu sử dụng. OUT chỉ được gọi giờ ra khi semantics checkout được chứng minh; không tự dùng last_seen làm checkout. Seed/default giờ không được coi là lịch khách hàng.
3. **Định nghĩa customer:** source hiện chưa đủ cho traffic chính xác. Hướng ưu tiên đã có trong master task là entrance line + IN + track/session dedup, camera quầy không cộng khách. Còn cần chốt người đã ra rồi quay lại trong ngày được tính lượt mới hay chỉ một người/ngày. Không yêu cầu FaceID/re-identification mọi khách để làm chart. Chưa có dữ liệu chính xác thì traffic chart/KPI phải thể hiện chưa có dữ liệu đã kiểm chứng.

Không hỏi lại policy Owner/Admin provisioning, không public registration, tối đa bốn AI camera đồng thời, bốn display slot không giới hạn registry, hoặc một camera thuộc một cửa hàng/khu vực: các mục đó đã được người dùng chốt.

## Focused QA trong sandbox của checkpoint audit

| Check | Kết quả |
| --- | --- |
| `node tests_browser/auth_account_ui.test.cjs` trực tiếp | PASS: 10/10, 0 fail. |
| `node tests_browser/media_lifecycle.test.cjs` trực tiếp | PASS: 45/45, 0 fail. |
| `node --check frontend/js/app.js` | PASS. |
| `node --check frontend/js/btmh_media_v5410.js` | PASS. |
| Git working-tree audit | BLOCKED: executable/metadata không có tại vị trí đã kiểm tra. |
| Pytest, full AI regression, real database/camera/browser preview | Không chạy trong audit này. Không dùng kết quả checkpoint cũ làm PASS mới. |

Không có command ngoài sandbox, escalation hoặc retry vô hạn. Không có focused test FAIL trong lần chạy này. Các kết quả trên chỉ giữ baseline UI/media, không chứng nhận các yêu cầu master task còn thiếu.

**NEEDS WINDOWS/HARDWARE ACCEPTANCE:** bốn camera AI thật đồng thời và fairness/capacity; browser đóng mà AI tiếp tục; bbox/tọa độ/resize/fullscreen với media thật; người thật IN/OUT/quay lại và nhiều camera; attendance theo ca và mất camera; PostgreSQL/migration và lịch sử cũ; RBAC nhiều cửa hàng; GPU/overload/soak. Chưa nói DONE hoặc production-ready.

**DỪNG trước implementation theo mục 2 của master task**, chờ quyết định nghiệp vụ và phạm vi migration. Sau câu trả lời mới lập ExecPlan và đi từng phase được yêu cầu.
