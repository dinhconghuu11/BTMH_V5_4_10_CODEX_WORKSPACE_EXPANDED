# FINAL REPORT — BTMH demo production-lite — 2026-10-08

Đã hoàn tất implementation và bounded critique/polish trên source hiện tại. Focused checks đã PASS; không có FAIL chưa xử lý. Current rendered QA/full framework và nghiệm thu cài đặt/thiết bị vẫn BLOCKED/PARTIAL như bên dưới. Không tuyên bố bản demo production-ready khi chưa nghiệm thu camera thật.

## 1. Source khi tiếp tục và phạm vi

Tiếp tục canonical source `PROJECT/BTMH_SYSTEM/` từ audit/ExecPlan/checkpoint hiện có. Không làm lại login, không rollback/discard/reset/clean; giữ launcher, recorder, native MediaMTX/WebRTC, camera registry và FaceID/PAD thresholds. Không chạy lệnh ngoài sandbox. Git/PATH/metadata không khả dụng ở checkpoint này; manifest dưới đây được đối chiếu theo source và checkpoint, không phải kết quả `git diff`.

Khi resume: attribution/background AI/4 slots/appearance/attendance/entrance visits/history đã DONE ở source; dashboard/account/camera UI và QR còn PARTIAL; critique/polish cho màn hình mới chưa bắt đầu. Tiếp tục trực tiếp các phần đó và sửa các regression/race được focused review xác nhận. Các phần đã PASS được giữ.

## 2. DONE / PARTIAL / BLOCKED

**DONE ở source và focused tests:**

- Camera/store/zone attribution, tên hiển thị độc lập camera ID; lưu lịch sử tại thời điểm event.
- Bốn display slots linh hoạt; multi-person bbox/label; recent recognition bounded.
- Appearance `#NNNN` riêng camera/ngày, concurrency-safe, Unknown → Verified giữ cùng appearance/event/#.
- Background AI admission độc lập UI, capacity và retirement guards, latest-frame và bounded model jobs/tracks.
- Chấm công theo ca thật/effective date/overnight, IN/OUT thật và dedup; history/query/CSV theo filter thật.
- Entrance visit/session logic, báo cáo ngày trước/ngày chọn theo cửa hàng, dashboard dữ liệu thật và readiness trung thực.
- Account menu/logout thật, profile/password/provisioning dùng auth/RBAC hiện có; không public registration.
- Camera configuration trong module hiện có; customer UI không chứa transport/decoder/FPS/raw camera source diagnostics.
- QR + desktop cùng staged enrollment và Owner/Admin approval, đúng hai bảng mới.

**PARTIAL / NEEDS ACCEPTANCE:** độ chính xác với người thật, bốn camera/GPU/overload/decoder retirement soak; installed PostgreSQL và khóa crypto thật; iOS/Android/trusted HTTPS/LAN; current rendered layout/keyboard/computed-style. Source tests không đủ để gọi những phần này production-ready. Không có module chức năng độc lập nào bị bỏ lại NOT STARTED; các mục nghiệm thu dưới đây còn mở.

**BLOCKED đã quan sát trong sandbox:** pytest/tool dependency access; Node subprocess test runner EPERM; một số `.pyc` replacement WinError5; full FastAPI/Pydantic import bị PermissionError ở `typing_extensions.py`; Git không khả dụng; browser kết nối không có ở checkpoint. Direct stdlib/Node checks tiếp tục chạy được. Không escape sandbox.

## 3. Camera, recognition và `#NNNN`

Camera registry hiện có vẫn là canonical source; display name do quản trị viên đặt và không thay identity. Camera gắn cửa hàng và `zone_name` hiện có. Event đóng băng camera/store/zone/name/time; đổi tên/chuyển cửa hàng không suy ngược làm sai lịch sử. Legacy thiếu attribution vẫn thiếu, không backfill từ mapping hiện tại.

Bốn slot là vị trí VIEW/FOCUS, không phải bốn camera cố định hay giới hạn registry. Chuyển một slot cleanup owner cũ của slot; không thay cấu hình AI, không restart các slot khác/backend. Overlay sử dụng detection/tracking hiện có, không decode video lần hai; map xywh/legacy xyxy theo kích thước source, object-fit, letterbox/crop, mirror, resize/fullscreen và clip tọa độ không hợp lệ. Mỗi track có bbox/label ba dòng: sequence, tên/kết quả, trạng thái FaceID/PAD.

Một `#NNNN` là **một appearance của một camera trong một ngày địa phương**, gồm nhân viên/khách/chưa xác định. Cùng appearance liên tục giữ số; Unknown → Verified cập nhật cùng event. Reacquire ngắn cần bằng chứng thời gian/hình học duy nhất, không gộp người chỉ bằng suy đoán. Counter khóa theo `(camera_id,business_date)` và atomic UPSERT/RETURNING; unique index chống trùng. Qua 00:00 theo timezone cửa hàng, appearance của ngày mới bắt đầu `#0001`; event ID thật không reset. `#NNNN` tuyệt đối không được dùng làm số khách.

Recent panel giữ tối đa 20 mục, upsert theo appearance; backend bounded/scoped và ảnh qua route được bảo vệ. History đầy đủ nằm trong DB. UI/poll/socket cleanup khi đổi trang, logout, pagehide/hidden; việc cleanup presentation không dừng background AI-active.

## 4. Background AI và overload

Supervisor lấy AI-enabled từ persisted camera configuration; demo tối đa bốn pipeline đồng thời. Reuse primary capture, các camera khác có capture/WalkBy state riêng, chia sẻ budget model hữu hạn. Camera được admission vẫn AI khi không nằm trong slot, đổi trang hoặc không có browser. ACTIVE / WAITING_FOR_CAPACITY / DISABLED / OFFLINE là trạng thái thật; reader/model retirement chưa chứng minh hoàn tất thì không mở camera thứ năm.

Latest-frame thay frame cũ; latest-batch hữu hạn, generation/age guards, track/sample/cache limits; mặc định tối đa 32 tracks/camera và hai concurrent PAD/two FaceID lanes. Known/candidate employee jobs được ưu tiên trước anonymous sampling. Guard cadence NORMAL/BUSY/OVERLOAD giảm inference sampling theo tải hiện có, giữ video path tách biệt. Identity cache/revalidation/quality/cooldown được reuse; DB recognition là appearance, không một row/frame. Race chờ `_ai_work_lock` sau handover được sửa bằng recheck gate/generation/pause/hold/PTZ bên trong lock. Không đổi model/security threshold hoặc tắt PAD.

## 5. Attendance và lịch sử

Giờ vào: valid IN đầu tiên thuộc employee/store/ca/business date phù hợp. Thấy nhân viên liên tục cập nhật last_seen, không tạo IN mới. OUT hợp lệ từ entrance đóng interval; IN sau OUT mở interval mới, không mất first IN. Mất camera/track không tạo checkout. Thiếu OUT hiển thị Chưa ghi nhận ra/Lần ghi nhận cuối, không lấy last_seen − first_seen làm giờ làm. Approved correction được ghi nguồn riêng, không giả camera OUT.

Ca/effective assignment/overnight/timezone lấy từ dữ liệu thật. Đi muộn dùng grace của schema, không hard-code giờ vào hay grace mới; thiếu ca/grace có trạng thái trung tính. Chỉ Vắng sau ca kết thúc mà không có valid IN. Dedup theo employee/store/shift/business date/state, không theo số camera/frame.

Nhận diện/chấm công/lượt ghé có date range, ngày/tháng/năm, store/zone/camera và filter nghiệp vụ phù hợp. Store scope thực thi SQL trước count/page/export. CSV lấy toàn bộ dữ liệu khớp filter, UTF-8 BOM và chống spreadsheet formula injection. Timeline dùng event IN/OUT/correction/observation thật, hỗ trợ ca qua đêm. Read-only Mobile Viewer history tương thích, không nhận quyền quản trị hay QR authority. Legacy visitor observations được gọi là quan sát, không lượt khách; hàng legacy không có attribution không được gán cho restricted store bằng camera hiện tại.

## 6. Lượt khách và dashboard

Metric là **lượt ghé/visits**, không unique persons. Chỉ camera entrance được cấu hình visitor counting + ROI/line/direction mới đóng góp. Valid visitor IN mở session và +1; không cộng lặp khi còn trong session. OUT thật đóng; IN mới sau OUT là lượt mới. Mất track/restart/midnight không giả OUT hoặc lượt mới. Employee/PAD-spoof không được tính visitor; Unknown → employee sửa classification và không replay stale crossing sau PAD recovery.

Không dùng detection frame, sequence hoặc legacy observation session để đếm khách. Anonymous cross-camera unique identity không được triển khai/khẳng định. Demo yêu cầu một counting camera có thẩm quyền cho cửa vào chồng lấn. Geometry hiện dùng face-visible tracking, cần camera/line phù hợp và người thật nghiệm thu.

Dashboard: scoped store, nhân viên có mặt/chưa ghi nhận/vắng/đi muộn theo schedule thật, camera/status/incident/recognition thật. So sánh visits theo frozen business date/timezone, chênh lệch và % zero-safe; không biến mẫu số 0 thành tăng 100%. Offline/capacity/chưa cấu hình biểu thị coverage/readiness PARTIAL, không fake 0 hay fake KPI. Lịch sử vẫn giữ khi current counting config bị tắt.

## 7. Account và UI

Owner/Admin tạo system account bằng fields schema hiện có, password confirm, role/store scope được backend kiểm tra. Login không có public registration; QR employee capture là flow khác. Account menu dùng tên/vai trò thật; logout gọi API/session thật và cleanup media/WebRTC/WebSocket/timers/QR views. Profile chỉ thay display name; đổi password cần current password và existing SMS/TOTP step-up, revoke sessions/trust/challenges và đăng nhập lại.

Giữ login đã redesign tốt. Các màn hình mới theo wine/ivory/gold nhẹ và system font local; không bổ sung sidebar module hoặc ảnh/claim giả. Normal camera UI chỉ LIVE/đang kết nối/mất kết nối/không khả dụng và business AI/PAD/recording states. Admin technical details mặc định đóng và có quyền; backend diagnostics được giữ.

Impeccable dùng hai isolated agents A/B; A hoàn tất trước khi findings B tới parent. A source assessment26/40 trước polish; không tự nâng score sau sửa. Snapshot và trend lưu thành công tại [critique snapshot](../.impeccable/critique/2026-10-08T13-45-13Z__frontend-index-html.md), priorities đã sửa và snapshot đóng. Đã khôi phục dashboard UTF-8, tách blocked verification trong recent, giữ camera draft trong RAM cùng actor/camera và clear khi mất quyền, nhóm secondary filters/reset/auto-apply rõ ràng, deduplicate polling/capture live announcements. Mobile không có dấu success cố định khi rejected/expired/cancelled; reason review bắt buộc được ghi rõ và có disabled-prerequisite explanation. Giữ label semantics trên video và toàn bộ backend decisions.

Detector chạy một lần mỗi markup: index exit2/nine findings, enroll exit0/zero. Full JSON/stderr trong [B evidence](../.impeccable/critique/assessment-b-evidence-20261008.json). Six runtime image slots, hierarchy do external CSS unresolved và em-dash placeholders được source-classify là false positives; playback contrast candidate ngoài scope được giữ lại. Có12/1 unresolved stylesheet warnings nên không suy rendered quality từ detector. Ignore list absent. Browser inventory actual `apps=[]/browsers=[]`; no fresh tab/visibility/injection/console/overlay vì không có surface. Không live server được mở; cleanup server N/A. Temporary critique body/source-check script đã xóa; evidence artifacts giữ chủ ý. Reused detector results, không parent rerun. Questions skipped: người dùng đã chốt scope/brand và yêu cầu hoàn thành rồi dừng.

## 8. QR migration, token và approval

Audit: **2 bảng mới** `face_enrollment_requests`, `qr_enrollment_invites`; **4 index**; **0 sửa schema cũ; 0 destructive operation; 0 data migration; 0 database thứ hai**. Source migration additive/idempotent. Không chạy migration lên customer DB trong task. Xem [QR_MIGRATION_AUDIT_20261008.md](QR_MIGRATION_AUDIT_20261008.md) cho SQL chính xác và evidence boundary.

Flow: Owner/Admin tạo nhân viên → chọn enrollment store hợp lệ → tạo token/QR → nhân viên consent và capture → encrypted PENDING → APPROVE / REJECT / REQUEST REENROLLMENT. Chỉ APPROVE publish existing encrypted template/index. Template cũ tiếp tục hoạt động trong pending/reject/reenrollment; existing withdrawal/deletion vẫn thu hồi đúng policy.

Token random server-side one-time, hashed-only trong DB, employee/request/store-bound, expiry/revocable; QR chứa opaque secret trong URL fragment, không password/embedding/PII. Redeem atomic; HttpOnly/Secure/SameSite Strict cookie authority hẹp cho capture, không portal/Viewer login. Invitation default 15 phút (5–60), capture deadline cố định 30 phút, submitted review 72 giờ. Reset/retry không kéo dài deadline. HTTPS + exact origin + JSON + bounded rate/body required. Không hard-code IP/camera credentials, không external QR service. QR từ HTTP có cảnh báo chưa dùng được trên điện thoại; không fake HTTPS/certificate.

Mobile là capture device: server dùng cùng registry quality/pose/two-pass/PAD/duplicate pipeline. Exactly one face, size/sharpness/exposure/pose/vertical coverage và current PAD PASS; camera refusal/offline/expiry/blocked PAD có recovery truthfully. Desktop cũng stage trước approval, không còn direct-finalize/client override bypass. Store đăng ký là request context, không tạo HR assignment.

Owner/Admin role + permission/scope/consent/revision được recheck từ DB. Unique active request/employee; SQLite BEGIN IMMEDIATE/process lock và PostgreSQL advisory transaction lock serialize decisions. Duplicate recheck current active templates trong publish transaction; explicit override cần reason. REENROLL tạo request/token mới và terminalize request cũ trong cùng hai bảng. Reset purge RAM trước cấp revision mới; post-commit portrait kiểm tra current consent/exact template trên cùng transaction để không resurrect sau withdrawal hoặc ghi đè approval mới.

Rollback path vận hành: `BTMH_QR_ENROLLMENT_ENABLED=0`, normal application restart; giữ hai bảng và old active templates, không tự DROP/restore/rollback DB. Dừng new QR/admin/staged desktop enrollment; không dừng recognition cũ. Approved runtime replacement là hành động nghiệp vụ, không migration rewrite.

## 9. Files changed — manifest theo checkpoint/source

| Files trong canonical source | Mục đích |
|---|---|
| `module_app/demo_context.py`, `db.py`, `production_ops.py`, `platform_v5.py` | Additive attribution/configuration và existing-schema integration. |
| `ai_camera_runtime.py`, `camera.py`, `walkby.py`, `camera_handover_v544.py` | Background admission, finite jobs/tracks, handover/generation/retirement safety. |
| `camera_appearances.py` | Atomic daily camera counter, stable appearance/event/dedup. |
| `shift_attendance.py`, `hr_reporting.py`, `office_engine.py` | Assigned-shift/IN/OUT/state integration; observation không là checkout. |
| `entrance_visits.py`, `visit_reports.py`, `recognition_history.py` | Entrance sessions, true visit metrics, scoped history/CSV/timeline. |
| `account_service.py`, `auth.py` | Existing auth/RBAC provisioning, profile/password atomic guards. |
| `qr_enrollment.py`, `qr_enrollment_routes.py`, `enrollment_capture.py`, `registry.py`, `student_media.py` | Exactly-two-table staged workflow, shared preparation, HTTP/body/rate/TLS gates, consent/publication/portrait race guards. |
| `main.py` | Scoped APIs/startup/integration, staged legacy capture, safe DTOs, Viewer compatibility. |
| `frontend/index.html`, `frontend/enroll.html`, `frontend/js/app.js` | Existing shell/navigation integration, explicit store, pending/review UI và lifecycle. |
| `frontend/js/btmh_media_v5410.js`, `frontend/css/btmh_media_v5410.css`, `frontend/js/btmh_v4.js` | Bbox mapping/labels và customer-facing media status cleanup. |
| `btmh_recognition_slots`, `btmh_recent_recognition`, `btmh_demo_reports`, `btmh_management`, `btmh_camera_configuration`, `btmh_account_profile`, `btmh_qr_enrollment_admin`, `btmh_mobile_enrollment` in `frontend/js/*.js` + `frontend/css/*.css` | Scoped operate screens, finite lifecycle, protected preview/approval/mobile flow. |
| `frontend/css/btmh_account_ui_v550.css`, `btmh_auth_ui_v550.css`, `btmh_design_v550.css` | Earlier brand/auth/account checkpoint retained; no new broad redesign. |
| `tests_demo/test_*.py` corresponding to the modules above; `tests_browser/*` listed below | Narrow SQL/state/thread/VM geometry/lifecycle/security checks; diagnostics fixture now loads actual QR cleanup helpers. |
| `PRODUCT.md`, `DESIGN.md`, `docs/EXECPLAN_DEMO_PRODUCTION_LITE.md`, `MASTER_RESUME_STATUS_20261008.md`, QR proposal/audit, this report, `.impeccable/critique/*` | Preserved product decisions, acceptance/checkpoint/evidence. |

Paths without `module_app/` prefix in the first ten rows share that folder. This manifest includes earlier MASTER changes kept on resume and current completion work; it is not an assertion that all rows were edited in this last turn.

## 10. Focused tests — PASS / FAIL / BLOCKED

Checks ran per phase in sandbox. Unchanged passing phases were not rerun merely to produce a larger regression count. Python direct `-B` stdlib tests use isolated SQLite/fixtures; Node runs files directly, not the blocked child-process runner.

| Suite | Actual latest focused result |
|---|---:|
| `tests_demo/test_demo_context.py` | PASS 10 |
| `test_ai_camera_runtime.py`, `test_demo_handover.py`, `test_camera_gate_race.py` | PASS 12 / 6 / 4 |
| `test_camera_appearances.py` | PASS 17 |
| `test_shift_attendance.py`, `test_entrance_visits.py` | PASS 18 / 29 |
| `test_recognition_history.py`, `test_visit_reports.py`, `test_account_service.py` | PASS 15 / 18 / 13 |
| `test_qr_enrollment.py`, `test_enrollment_capture.py`, `test_qr_enrollment_http.py`, `test_qr_integration_review.py` | PASS 18 / 12 / 17 / 5 |
| `test_demo_api_scopes.py` current final gate | PASS 30 |
| `tests_browser/recognition_slots.test.cjs`, `media_overlay.test.cjs`, `media_overlay_labels.test.cjs`, `recent_recognition.test.cjs` | PASS 11 / 7 / 4 / 13 |
| `demo_reports.test.cjs`, `camera_configuration.test.cjs`, `customer_diagnostics_ui.test.cjs`, `account_profile.test.cjs` | PASS 25 / 17 / 8 / 11 |
| `mobile_enrollment.test.cjs`, `qr_enrollment_admin.test.cjs`, `desktop_enrollment_review.test.cjs` | PASS 22 / 25 / 13 |
| `management_dashboard.test.cjs`, `auth_account_ui.test.cjs`, `system_diagnostics_lifecycle.test.cjs` current final gate | PASS 8 / 10 / 24 |
| Earlier relevant `media_lifecycle.test.cjs`, `v4_frontend_lifecycle.test.cjs` | PASS 45 / 44 at retained checkpoint |
| Changed Python `compile(source)`, frontend JS syntax, scoped UTF-8/control-ID/live-region/result markup checks | PASS; no `.pyc` write required; markup check is not render acceptance |

**FAIL:** no unresolved failure in completed focused gates. Initial diagnostics final run had 14 FAIL because its isolated VM omitted the new production QR helpers; fixture imported actual helpers/dependencies and added teardown assertions, then24/24 PASS. The new mobile announcement test initially inspected before the actual350ms scheduled upload; it now advances that timer and all22 PASS. A native Windows `python -c` source-check invocation lost nested argument quotes; file-based source check passed and its temporary script was removed. Other implementation-phase failures were corrected before their PASS checkpoint.

**BLOCKED:** pytest/access dependencies; Node `--test` child-process EPERM; `.pyc` replacement ACL; current full FastAPI/Pydantic/ASGI integration; current rendered browser QA; Git diff. `VERIFY_RELEASE.py`/unrelated broad regression were not run under the user's focused-test instruction; not described as PASS. No attempt to escape sandbox.

Crypto in service/capture tests uses an isolated authenticated test adapter because installed cryptography is unavailable in this interpreter. Production existing crypto code was not changed; test PASS is not installed-key/Fernet validation. HTTP adapter tests include actual ASGI body guard receive/send execution and QR encode/decode, but substitute framework integration; no server/network/end-to-end claim. Model/camera behavior in pure tests is controlled; no hardware PASS.

## 11. Nghiệm thu Windows / camera / điện thoại / HTTPS

1. **Windows + existing DB:** backup bằng quy trình vận hành, startup/migration idempotent trên bản test database hiện có; xác nhận QR chỉ thêm hai bảng/four indexes, old FaceID/attendance/camera/users còn tương thích. PostgreSQL concurrent redemption/approval và rollback transaction; installed crypto keys đọc old/new templates; feature disable không mất old recognition.
2. **Bốn camera thật:** configured registry >4; max4 AI admitted, fifth waiting, offline/recovery truthful. Đổi slot/chuyển trang/logout/đóng browser vẫn có event từ AI-active camera đang không hiển thị. Handover và decoder/model retirement soak không vượt capacity hoặc leak workers.
3. **Multi-person/bbox:** nhiều người đồng thời, khác aspect/resolution, resize/2x2/fullscreen/mirror; mỗi người một box/label không lệch hoặc che mặt. Cùng appearance ổn định; Unknown → Verified cùng #; short loss/reacquire không spam; mỗi camera counter riêng; qua 00:00 bắt đầu ngày mới nhưng event IDs không reset.
4. **Load/security:** đông người/GPU tải thật, latest-frame/drop bounded, employee priority, NORMAL/BUSY/OVERLOAD, UI/video responsive; PAD spoof checks và thresholds giữ nguyên. Đo fairness/latency/retirement/soak thực tế trước production-ready claim.
5. **Attendance:** assigned/effective/overnight/grace thật; cross-camera dedup, real IN/OUT/reentry, missing OUT và camera-loss không fake checkout; absence chỉ sau ca; CSV/timeline đúng filter/data. Camera rename/move không đổi lịch sử cũ.
6. **Visits:** camera cửa vào có line/ROI/direction và face-visible coverage phù hợp; đứng yên không cộng, OUT→IN thêm lượt mới, track loss không tạo lượt, employee/spoof không tính. Không dùng #/legacy observations/unique persons; overlapping entrances chỉ có counting authority đã thống nhất. Xác nhận đủ độ tin cậy trước demo số khách với khách hàng.
7. **Phone LAN/HTTPS:** DNS/address do quản trị viên cấp, certificate hợp lệ và được iOS Safari/Android Chrome tin cậy; không bypass certificate warning. Wi-Fi, permission denied/no camera, offline/resume, expiry/reuse/revoke, two-pass pose/quality/PAD thật, duplicate feedback, pending receipt và fallback đăng ký tại quầy.
8. **Approval/compatibility:** Owner/Admin đúng scope approve/reject/reenroll; unauthorized blocked; old template vẫn hoạt động khi pending/rejected; new template chỉ active sau approve; duplicate override reason/audit; consent withdrawal/deletion không resurrect portrait; restart pending/revoked token không publish; stale/concurrent decisions không double approve.
9. **Rendered UI/accessibility:** current desktop 1440/tablet768/mobile390 và short viewport, keyboard/focus return, zoom/long Vietnamese names, tables/filters/QR controls, loading/empty/error/permission states. Prior auth screenshots chỉ chứng minh checkpoint cũ.

Không chạy migration/customer runtime/thiết bị thật từ task này. Sau report hoàn tất, dừng; không tự mở thêm phạm vi.
