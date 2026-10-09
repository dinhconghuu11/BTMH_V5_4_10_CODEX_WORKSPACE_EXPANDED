> Báo cáo lịch sử của checkpoint ban đầu. Người dùng đã cấu hình lại camera; giới hạn ảnh/presentation bên dưới đã được sửa trong phần tiếp nối. Xem [báo cáo realtime mới nhất](FINAL_REPORT_REALTIME_RECOGNITION_20261009.md) để biết trạng thái hiện tại, tests và các mục chưa nghiệm thu trên camera thật.

# BTMH V5.4.10 — Camera LIVE nhưng chưa nhận diện AI

Ngày: 2026-10-09. Tiếp tục từ checkpoint camera AI; không làm lại MASTER hoặc offline installer.

## 1. Nguyên nhân chính xác

**Nguyên nhân hiện tại là cấu hình AI chưa bật và camera chưa được gán cửa hàng.** Diagnostic đã thực sự đọc PostgreSQL bằng transaction readonly, dùng Python runtime đã cài ở profile Windows. Kết quả khớp tên và trạng thái trong ảnh:

| Camera | Bật camera | AI | Cửa hàng | Khu vực | Đủ điều kiện nhận worker |
|---|---|---|---|---|---|
| ID 1 — Laptop Camera | Có | Tắt | Chưa gán, 0 assignments | Máy vận hành | Không |
| ID 2 — Hikvision DS-2CD1123G0-IUF | Có | Tắt | Chưa gán, 0 assignments | Hikvision LAN | Không |
| ID 3 — WyreStorm CAM001 | Có | Tắt | Chưa gán | Chưa gán phòng | Không |
| ID 4 — Camera PTZ | Có | Tắt | Chưa gán | Chưa gán khu vực | Không |

AI admission hiện có yêu cầu camera enabled, `ai_enabled=true`, đúng một assignment tới cửa hàng hợp lệ và khu vực không rỗng. Browser LIVE/ghi hình/chọn một trong bốn ô không bật AI. Supervisor chỉ cấp worker cho camera đủ điều kiện; do đó video vẫn có hình nhưng metadata chưa có tracks/boxes/results cho nhận diện.

Profile có cửa hàng ID 1, tên “Cửa hàng mặc định”. Người quản lý cần chọn cửa hàng đúng nghiệp vụ; Codex không tự chọn, gán hay bật AI. Owner/Admin có quyền `*`; TECHNICIAN có `camera.configure` nhưng vẫn bị store scope kiểm tra. Phiên/tài khoản trình duyệt hiện tại không được đọc, nên chưa xác nhận quyền của actor đang đăng nhập.

Ba model bắt buộc YuNet/SFace/MiniFASNet PAD có mặt, đúng hash, và load thực tế thành công trong tiến trình kiểm tra riêng bằng runtime đã cài. `MODULE_CAMERA_MODE=service`, `MODULE_AI_NATIVE_FRAME=1`, PAD/device-context dùng default bật. Hai model YOLO tùy chọn và ultralytics/torch chưa có; FaceCore dùng YuNet chính và SFace, nên sự thiếu YOLO này không giải thích trạng thái “AI chưa bật”. Không thay đổi cơ chế fallback hoặc PAD.

| Phân loại | Kết luận |
|---|---|
| Cấu hình | **Đã xác nhận:** AI tắt và thiếu store assignment cho cả Laptop/Hikvision |
| AI worker | Không đủ điều kiện admission theo cấu hình; chưa quan sát worker memory trong server đang chạy |
| Inference/model | Required models load PASS riêng; xử lý frame thật trong server sau bật AI chưa nghiệm thu |
| Backend/API | Metadata dùng worker của đúng camera, giữ quyền/store scope; đã sửa availability và cached-track publication |
| Frontend | Đã xác nhận thông báo chờ/Ready/0% không giải thích AI disabled; đã sửa |
| Môi trường | Sandbox không kết nối được HTTP localhost host; **không kết luận Production ngừng hoạt động**. PostgreSQL readonly và model-load kiểm tra riêng đã thành công |

Progress 0% trước đây mô tả trạng thái xác minh danh tính, không phải tiến độ khởi động model hay AI FPS. Khi không có metadata, UI cũ vẫn ghi “Đang chờ dữ liệu nhận diện”/“Sẵn sàng”. Không có worker hợp lệ thì không có bbox/name/event mới để hiển thị. Nhân viên chưa có FaceID hoặc chưa qua PAD cũng không được tự gán danh tính hay ép tiến độ 100%.

Evidence: [runtime snapshot](CAMERA_AI_RUNTIME_EVIDENCE_20261009.json).

## 2. Các sửa source đã chứng minh cần thiết

- Tách `ai_error_code` khỏi lỗi capture: video mới không xóa lỗi `AI_PROCESS_FAILED`.
- AI FPS/count chỉ tính kết quả xử lý thành công, không tính attempt lỗi hoặc generation đã bị loại. Success của source trước không làm source mới thành ACTIVE; cảnh trống xử lý thành công vẫn là ACTIVE.
- Worker đang lỗi/tạm dừng/chưa xử lý thành công báo ERROR/PAUSED/STARTING, thay vì suy ra ACTIVE từ video online. Admission/capacity/retirement/scheduling giữ nguyên.
- Public metadata chỉ gửi reason/error codes trong allowlist; không gửi exception text/source credentials. AI không ACTIVE thì không phát lại identity/bbox cũ.
- UI camera và selected panel giải thích disabled/missing store/zone/error/pause/start/offline/capacity, giữ trạng thái verification thật. Sau người dùng lưu cấu hình, UI đọc lại runtime state để không giữ badge DISABLED cũ; không tự retry thao tác lưu.
- Hoàn tất diagnostic chỉ đọc, stdout UTF-8, không sinh bytecode, không import/start app/camera, không migrate DB và không chọn source/password/token/face data trong query.

Không thay ngưỡng, model, FaceID/PAD decisions, #NNNN, camera sources, cấu hình vận hành, business events, attendance hoặc counting. Không cung cấp fake recognition cho Production. Các fixes không tự bật hai camera; vẫn cần lưu cấu hình đúng trên website.

## 3. Files changed trong nhiệm vụ camera AI

| Nhóm | File |
|---|---|
| Worker/status | `module_app/camera.py`, `module_app/ai_camera_runtime.py` |
| Status/metadata API | `module_app/main.py` |
| Chẩn đoán readonly | `scripts/diagnose_camera_ai.py` |
| UI hiện có | `frontend/js/app.js` (selected recognition panel), `frontend/js/btmh_recognition_slots.js`, `frontend/js/btmh_camera_configuration.js` |
| Focused Python tests | `tests_demo/test_ai_runtime_status.py`, `tests_demo/test_camera_gate_race.py`, `tests_demo/test_ai_diagnosis_contract.py`, `tests_demo/test_demo_api_scopes.py` |
| Focused Node tests | `tests_browser/recognition_slots.test.cjs`, `tests_browser/camera_configuration.test.cjs` |
| Checkpoint/report | `docs/EXECPLAN_CAMERA_AI_DIAGNOSIS_20261009.md`, `docs/CAMERA_AI_RUNTIME_EVIDENCE_20261009.json`, báo cáo này |

Git CLI không có trong PATH và không có `.git` ở workspace/source; không lấy được status/diff. Không rollback/discard thay đổi có trước; không sửa pytest file đang mở trong IDE.

## 4. Tests PASS / FAIL / BLOCKED

| Test mới thực sự chạy | Kết quả |
|---|---:|
| AI telemetry/error/empty scene/current epoch | 9 PASS |
| Camera gate race | 4 PASS |
| AI admission/background ownership/latest batch | 12 PASS |
| Readonly diagnostic + public metadata/stale identity | 8 PASS |
| Selected camera/fleet/metadata/recent store-scope contracts | 4 PASS |
| `tests_v54/test_ai_camera_v550.py` — registry/private stream/frame evidence/handover | 13 PASS |
| Node recognition slots | 14 PASS |
| Node camera configuration/readback/explicit save/late auth cleanup | 21 PASS |
| Adjacent Node recent recognition | 13 PASS |
| Adjacent Node auth routing | 11 PASS |
| Compile changed Python / syntax changed JS | 8 Python + 3 JS PASS |
| Real PostgreSQL readonly diagnostic | PASS; camera configuration/roles inspected; no migration or write |
| YuNet/SFace/PAD runtime model load | PASS in separate process; no camera inference performed |
| Actual host camera recognition/UI/WebSocket/soak | NOT RUN / pending user hardware acceptance |

Tổng focused suite: 50 Python tests + 59 Node tests PASS, không tính lại những lần rerun cùng test. Không có FAIL còn tồn tại trong phạm vi đã hoàn tất. Ban đầu test readonly có fixture parameter mismatch và CLI gặp Windows stdout encoding; đã sửa và rerun. Một lần gọi nhầm tên scope-test đã sửa lệnh và chạy đúng 4 tests PASS. Pytest có deprecation warnings hiện có; không refactor lifespan ngoài phạm vi. Không chạy lại toàn bộ MASTER/VERIFY_RELEASE.

## 5. Chức năng đã kiểm chứng và giới hạn

Đã kiểm chứng quyền/store filtering trong các route contracts, admission tối đa bốn worker và ownership nền trong tests hiện có, discard stale/generation/frame evidence, trạng thái error không bị video che, FPS chỉ tính success, selected-camera metadata không dùng identity cũ khi AI unavailable, và explicit configuration save/readback lifecycle.

Đã đọc cấu hình PostgreSQL thật, kiểm tra hashes/dependency versions bằng runtime thật và load ba model. Những việc này không chứng nhận đang xử lý camera thật trong tiến trình web. Chưa truy cập được phiên browser runtime, chưa quan sát frame/metadata/event mới sau cấu hình và chưa dựng kết quả để làm nghiệm thu PASS.

Nhánh truyền kết quả được giữ: camera capture → latest-frame AI → WalkBy FaceID/PAD → camera-scoped tracking metadata → media metadata event → bốn slots/selected panel. Recent appearances/events và ảnh dùng API `recognition/recent` với camera/store filtering; ảnh chỉ có khi đã lưu snapshot thật và actor có `evidence.view`. Kênh tracking nhẹ không nhúng ảnh sinh trắc vào mỗi packet. Không lấy ảnh hoặc danh tính từ camera khác để lấp trạng thái trống.

Giới hạn ảnh của panel đã xác định từ source: `renderRecognitionSlotSelection` hiện xóa `src` của ô ảnh lớn và chưa ghép snapshot từ API recent vào ô này. Vì vậy bật AI có thể cập nhật trạng thái/tên nhưng không bảo đảm ô ảnh lớn có ảnh. Lượt này giữ luồng ảnh recent/history hiện có; tích hợp ảnh vào selected panel chưa được sửa hoặc nghiệm thu. Đây là giới hạn frontend riêng, không phải bằng chứng inference thất bại.

## 6. Lệnh Windows

PowerShell, từ workspace (chỉ đọc profile; không cần gửi bất kỳ mật khẩu/token/RTSP URL):

```powershell
Set-Location 'C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM'
& "$env:LOCALAPPDATA\CampusFace\runtime\venv\Scripts\python.exe" -B .\scripts\diagnose_camera_ai.py
```

Nếu đang dùng profile legacy/custom, dùng Python runtime của profile đó và thêm `--data-root '<profile hiện có>'`; script tự nhận environment/legacy marker thông thường. Không dùng interpreter test/QA để suy ra packages của Production.

CMD tương đương cho profile mặc định:

```bat
cd /d C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM
"%LOCALAPPDATA%\CampusFace\runtime\venv\Scripts\python.exe" -B scripts\diagnose_camera_ai.py
```

Để nạp mã backend đã sửa, dừng backend đang chạy bằng Ctrl+C trong cửa sổ của nó, rồi từ source chính:

```powershell
.\START_CAMPUSFACE.bat
```

Mở lại `http://127.0.0.1:8100/` và Ctrl+F5. Codex chưa stop/restart server vận hành. Không chạy Preview hoặc tắt security/PAD để vượt kiểm tra.

Trong browser đã đăng nhập, có thể mở các URL **GET được bảo vệ bằng phiên hiện có** để đối chiếu, không thêm token:

- `/api/v1/recognition/cameras`: camera AI-enabled/store/zone, state/reason và current-source successful count.
- `/api/v1/cameras/fleet`: capacity/admission theo quyền; không đổi worker.
- `/api/v1/media/metadata?camera_id=1` và `camera_id=2`: state, source/camera sequence, result timestamp, bbox/tracks của đúng camera.
- `/api/v1/recognition/recent?limit=20&camera_id=1` hoặc ID 2: sự kiện/appearance đã ghi nhận và snapshot URL nếu đủ quyền.

HTTP 401/403 phải xử lý bằng đăng nhập/quyền đúng, không bypass. Không gửi raw cookies, bearer token, source hoặc credential log.

## 7. Các bước trên website và nghiệm thu camera thật

1. Đăng nhập Owner/Admin hoặc tài khoản được cấp `camera.configure` và store scope phù hợp. Mở **Xem trực tiếp → Quản lý camera**; đây là cấu hình camera, không phải dropdown đổi một ô nhận diện.
2. Chọn **Laptop Camera**, gán **cửa hàng đúng**, kiểm tra **khu vực**, tích **Nhận diện AI**, bấm **Lưu cấu hình**. Làm riêng cho **Hikvision**. Không bật đồng loạt camera chưa dùng; không thay đổi connection source/credentials hoặc bật đếm khách ngoài nhu cầu.
3. Nếu không có cửa hàng đúng, Owner/Admin tạo/cấu hình cửa hàng theo nghiệp vụ hiện có trước. Nếu form không có quyền, không dùng database edit để lách; người quản lý thực hiện assignment.
4. Quay lại **Nhận diện & chấm công → Tải lại**. Với mỗi camera đã bật, chờ trạng thái STARTING → ACTIVE sau khung hình xử lý thành công. ERROR/PAUSED/OFFLINE/capacity phải được xử lý theo trạng thái, không ép ACTIVE.
5. Đưa một rồi nhiều người thật vào khung hình: `camera_seq`, timestamp/result count phải tăng; `tracks` có bbox và UI vẽ đúng camera/geometry. Cảnh không có người vẫn có thể AI ACTIVE với tracks rỗng.
6. Người chưa có FaceID cần hiện unknown/unregistered; nhân viên được enrollment/phê duyệt mới có điều kiện nhận tên. Xác minh FaceID/PAD thật; thử ảnh/video spoof phải bị chặn hoặc chưa xác minh, không nhận tên chỉ vì detection thấy mặt.
7. Kiểm tra appearance #NNNN, Unknown → Verified giữ ID, không tạo nhận diện/attendance lặp; recent/history ghi đúng cửa hàng/khu vực/camera. Kiểm tra ảnh snapshot thật với quyền evidence; không mong ảnh từ kênh metadata nhẹ.
8. Đổi camera khỏi bốn ô, đổi trang/ẩn tab: backend của camera AI-active tiếp tục tạo kết quả/sự kiện khi đủ điều kiện; không mở worker/decoder trùng. Kiểm tra reconnect và shutdown sạch bằng camera thật.

Các bước trên là acceptance chưa chạy, không phải PASS được giả định. Nếu sau khi lưu đúng configuration mà vẫn không có results, đối chiếu metadata/count/reason với diagnostic; khi đó mới xác định capture, worker/inference hay transport cụ thể.

## 8. Vấn đề còn tồn tại

Hai camera vẫn AI-disabled/unassigned trong snapshot đã đọc; cần người quản lý lưu cấu hình đúng. Active web runtime chưa nạp changes cho tới restart. Real multi-face detection/boxes/labels/events/phone-spoof/PAD/background/duplicate acceptance sau bật AI chưa được quan sát. Browser localhost hạn chế không được dùng để kết luận website Production hỏng. Không có migration hay thay đổi nghiệp vụ chờ phê duyệt.

Hoàn tất phần chẩn đoán/source/tests độc lập; dừng sau báo cáo theo yêu cầu.
