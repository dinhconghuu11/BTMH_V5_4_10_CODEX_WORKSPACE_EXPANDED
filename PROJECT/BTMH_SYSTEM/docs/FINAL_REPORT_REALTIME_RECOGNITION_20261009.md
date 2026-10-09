# BTMH — tiếp nối nhận diện realtime, 2026-10-09

**PARTIAL: đã sửa và kiểm thử các lỗi source được tái hiện. Chưa đạt Commercial Acceptance; chưa chứng minh Hikvision hết bỏ sót hoặc FPS tăng trên camera thật.** Báo cáo này thay thế các giới hạn ảnh/presentation trong báo cáo camera AI trước đó; giữ nguyên bằng chứng lịch sử.

## Tiếp nối mới nhất — ảnh đã xác minh bị treo tải / Hikvision PAD

**Đã sửa hai lỗi source của recent/dialog:** ảnh được tạo với `hidden` và `loading=lazy`, trong khi chỉ `onload` mới hiện ảnh; Chrome có thể trì hoãn chính sự kiện cần để hiện nó. Dialog cũng bị dựng lại mỗi lần poll 2,5 giây, hủy lượt tải đang chạy và thu hồi ảnh vừa tải. Hai regression FAIL trước sửa; Chrome thực cũng tái hiện ảnh ẩn không decode trước sửa. Đã chuyển ảnh này sang eager (tải API vẫn giới hạn ba lượt), giữ node/owner ảnh khi dữ liệu dialog không đổi, cập nhật khi dữ liệu thật đổi và giữ nút Tải lại để thử lại lỗi tải. Auth, `evidence.view`, camera/store scope, abort và object-URL cleanup được giữ.

**Mẫu Production mới do người dùng gửi:** camera 2 ACTIVE, input HIKVISION_SUBSTREAM 640×360, detected/observed=1, observation_errors=0, AI 4 FPS đúng target 4; PAD completed=4/dropped=1/errors=0/pending=1; FaceID completed=0. Track đang VERIFYING_PASSIVE/PENDING, reason PAD_CHECKING, chưa có PAD scores, face_px=90/brightness=57,4/quality=0,6853. Đây là một mẫu đang chờ PAD, không phải mẫu BLOCKED ở screenshot. Chứng minh capture/detection và lane PAD có hoạt động; chưa chứng minh PAD PASS cho track hiện tại hay độ chính xác trên người thật. FaceID chưa được chạy khi PAD chưa PASS là admission bảo mật hiện có, không phải bằng chứng model FaceID lỗi. Counters là của lane, không đồng nghĩa cả bốn kết quả đã áp dụng cho track này.

PAD result latency 493,9 ms **nhỏ hơn** giới hạn hiện có 2 giây; queue wait 1,8 ms và inference 98,5 ms. Không kết luận timeout, kẹt worker hoặc false reject chỉ từ mẫu này. Screenshot "Không qua xác minh" chứng minh PAD đang chặn hiển thị danh tính; chưa xác định được nhánh neural/context và lý do chặn người thật. Cần sample khi BLOCKED hoặc chuỗi 30 giây có scores. Không sửa PAD/FaceID/model/crop/threshold để ép nhận diện.

**Lỗi telemetry đã sửa:** `substream_capture_fps=310,2` được copy từ readiness lúc vừa mở ba frame rồi giữ nguyên. Regression đã FAIL trước sửa. Giờ đo tốc độ frame decode đang nhận trong cửa sổ ít nhất một giây, tính cả frame bị latest-slot consumer bỏ qua; reset khi đổi decoder/source, trả 0 khi chưa có cửa sổ đo hoặc nguồn không ready. Đây là tốc độ frame đến decoder, không phải cam kết FPS sensor hay mức tăng tốc AI. Không đổi capture FPS, resolution hoặc scheduler.

**Validation lượt này:** 107 Node PASS (25 recent/evidence, 21 selection, 48 lifecycle, 7 geometry, 4 overlay, 2 benchmark privacy); 52 Python PASS (AI capture, retirement, model-lane mock contracts, read-only/public diagnosis); 5 JS syntax và 2 Python compile PASS. Chrome isolated **1 photo regression PASS**: PNG kỹ thuật 2×2 decode, card/dialog hiện ảnh, ba poll giữ node/URL, revoke quyền và logout dọn ảnh. QA không dùng mặt người, không tạo nhận diện giả, **0 HTTP API requests**. Evidence: `frontend/.qa_evidence_photos/visual-results.json`. Ba lỗi mới đã được tái hiện FAIL trước sửa. Camera thật/PAD false-reject/HTTP ảnh Production vẫn **PENDING**, chưa báo PASS.

**Files của lượt này:** `frontend/js/btmh_recent_recognition.js`, `frontend/index.html` (cache `photo2`), `module_app/ai_capture_v550.py` (chỉ FPS telemetry), `scripts/benchmark_camera_ai.js` (allowlist status/PAD scores), `tests_browser/recent_recognition.test.cjs`, `tests_browser/camera_ai_benchmark.test.cjs`, `tests_browser/visual_recognition_console.cjs`, `tests_v54/test_ai_capture_v550.py`, `.gitignore` và ExecPlan/report/checkpoint/evidence. Không thay database/camera configuration hay các logic nhận diện đã PASS.

**Nghiệm thu trên Windows:** phục vụ đúng workspace, Ctrl+F5 rồi mở một recent event đã xác minh có saved evidence; ảnh card và dialog phải hiện và vẫn giữ khi đợi ít nhất 10 giây. Nút Tải lại phải thử lại lỗi tải; revoke quyền/đăng xuất/đổi camera phải dọn ảnh. Event ANALYZING chưa có saved evidence vẫn được phép hiện "Chưa có ảnh". Nếu vẫn lỗi, ghi đúng HTTP status ảnh trong Network, không chia sẻ headers/cookie/token. Chỉ đổi frontend thì không cần restart backend. Để nạp sửa FPS Python, Ctrl+C trong terminal backend hiện tại rồi chạy launcher tại mục 7 một lần; Codex chưa restart Production.

Đo Hikvision-only khi có mặt thật bằng script GET tại mục 7: `await BTMHCameraAIBenchmark({cameraIds:[2], seconds:30})`. Script mới thêm status/pad_status/PAD scores, loại tên/mã người/source/bí mật; không thay camera/worker/security. Mẫu đang PENDING cần theo dõi tới PASS/BLOCKED. Chỉ điều tra matching/enrollment khi PAD PASS và FaceID thực sự completed; với BLOCKED, lấy reason/scores/quality của đúng track. Không coi LIVE hoặc bounding box là xác minh danh tính thành công.

## 0. Giao diện theo ảnh tham chiếu mới — đã hoàn thành trong source

Trang Nhận diện dùng bố cục nền tối: camera lớn bên trái; chi tiết người đang được xác minh và lịch sử gần đây bên phải; thanh chuyển camera ở dưới. Các trang và sidebar khác giữ nguyên. Thanh camera lấy registry được cấp quyền, đổi lựa chọn bằng card, dropdown hoặc nút trước/sau. Chỉ có một media owner; thumbnail của camera đang xem copy frame đã hiển thị. Camera chưa chọn dùng biểu tượng, không mở thêm luồng hoặc gọi API frame để tạo thumbnail.

Ảnh người vẫn tải từ saved evidence đúng event/camera/store và `evidence.view`. UI hiển thị placeholder khi chưa có ảnh hoặc chưa được cấp quyền. Không tạo người, ảnh, confidence, FPS hoặc recognition giả để giống hình minh họa. FaceID/PAD, #NNNN, background AI và recording không thay đổi trong phần UI này. Chấm công, bộ phận và hướng được giữ trong mục mở rộng **Chấm công & trạng thái**.

Files trực tiếp thay đổi cho UI: `frontend/index.html`, `frontend/css/btmh_recognition_console.css` (mới), `frontend/js/btmh_recognition_slots.js`, `frontend/js/app.js`; tests `tests_browser/recognition_slots.test.cjs`, `tests_browser/visual_recognition_console.cjs` (mới); cập nhật PRODUCT/DESIGN/ExecPlan/báo cáo/checkpoint.

**Kiểm tra của phần UI:** 102 Node PASS (21 selection/switch/thumbnail + 22 evidence/recent + 48 lifecycle + 7 geometry + 4 overlay labels), 4 JavaScript syntax PASS. Chrome headless với profile mới trong workspace: 390/768/1440/1920 px **4 PASS**, xác minh layout/overflow/hidden/16:9/focus, Enter đổi camera, cuộn tới chấm công. Đã xem screenshot desktop/tablet/mobile. QA dùng bốn card camera thử bố cục, feed recognition rỗng, không ảnh/người và **0 HTTP API requests**; không kết nối port Production 8100. Evidence/screenshot: `frontend/.qa_recognition_console/visual-results.json`, `desktop.png`, `wide.png`, `tablet.png`, `mobile.png`. Lần thử browser trong sandbox không tạo được inspection port; kiểm tra tĩnh sau đó chạy với auto-review cho phép profile riêng. Không thay policy xác thực hay sandbox của Production.

**Cách xem trên Production:** nếu server đang phục vụ workspace này, mở Nhận diện & chấm công và nhấn **Ctrl+F5**. Các static asset đổi cache version; không cần restart AI/backend chỉ cho phần giao diện này. Chọn Hikvision, kiểm tra video/box/tên thật, ảnh saved evidence và lịch sử; thử đổi Laptop rồi quay lại, tab ẩn và quay lại. Nghiệm thu tốc độ/độ chính xác Hikvision, ảnh HTTP thật và fullscreen với video thật vẫn **chưa PASS**. Bố cục mới không giải quyết thay cho phần inference còn cần số liệu hardware bên dưới.

## 1. Nguyên nhân đã xác định và phần chưa xác định

| Hiện tượng | Kết luận / bằng chứng |
|---|---|
| Ban đầu LIVE nhưng “AI chưa bật” | Snapshot registry ban đầu: AI disabled, chưa gán cửa hàng. Người dùng đã cấu hình lại; snapshot mới nhất camera 2 eligible, camera 1 AI off theo lựa chọn của người dùng. Codex không sửa database/cấu hình. |
| Hikvision đã bật nhưng panel vẫn báo AI off | Ảnh khi đó đang chọn Laptop; panel theo camera được chọn. Chọn ô xem không bật AI. Single view mới ưu tiên camera AI khi khởi tạo, vẫn giữ lựa chọn thủ công. |
| Ô ảnh lớn không hiện ảnh | Source cũ luôn xóa `src`, không nối saved event evidence. Đã sửa. |
| Các recent card “Chưa có ảnh” | Classified event 1003 và các event blocked có file snapshot thật. ANALYZING thường chưa có snapshot theo contract. Image errors cũ bị che dưới một placeholder; đã thêm authenticated loader/thông báo lỗi. HTTP 401/403/404 của browser thật **chưa được quan sát**, nên chưa khẳng định nguyên nhân của mọi card là lỗi xác thực. |
| Track có thể bị đổi người | Hai regression geometry FAIL trước sửa: observation rõ hơn chiếm track của người đứng yên; previous-box overlap lấn át motion prediction khi đi ngang nhau. Sau sửa PASS. Đây chưa phải bằng chứng nguyên nhân Hikvision bỏ sót detector. |
| Box Verified đứng nguyên khi mất metadata | Test tái hiện video vẫn LIVE, socket im lặng, box không hết hạn. Đã sửa expiry độc lập với packet tiếp theo. |
| Chi phí acquisition dư | Hai test trước sửa chứng minh copy main 1080p không dùng khi substream đã sẵn sàng, và copy frame stale trước khi bỏ. Đã tránh các bản sao này. Không suy ra mức tăng FPS từ việc bỏ copy. |
| Hikvision hiếm nhận được nhân viên, kể cả chỉ một camera AI | Người dùng cung cấp một sample: ACTIVE, 449 results, 640x360, AI 2.8 FPS/target 7, capture 18.1 FPS, avg 69 ms/p95 174.1 ms, result age 6.5 ms/source age 17.8 ms, tracks rỗng, PAD/FaceID completed=0/errors=0. Người dùng xác nhận có mặt trong LIVE. Điểm dừng nằm trước verification trong sample này; **chưa phân biệt detector miss, observation error hoặc khác chất lượng giữa main/substream**. Cần sample mới có `ai_detection` và `stage_times`. |

Hikvision đã từng có recognition thật với PAD PASS; các event khác bị multi-frame PAD chặn (ví dụ event 1035 có spoof score .9772). Không coi đó là bằng chứng người dùng giả mạo, cũng không tự kết luận model false-positive khi chưa có nghiệm thu. FaceID không được vượt PAD để ép hiện tên. Không có bằng chứng queue PAD/FaceID bị kẹt từ sample không có job.

## 2. DONE — implementation

- **Tracker hiện có:** ghép toàn cục một-một bằng minimum-cost assignment, giữ distance/size/gap gates hiện có; IoU dùng box dự đoán từ velocity. Đo velocity theo timestamp frame nhận được, giữ wall clock riêng cho absence/nghiệp vụ. Không thêm ByteTrack/SORT/model/dependency hay một pipeline song song.
- **Acquisition:** chỉ copy frame thực sự được chọn; main fallback vẫn cần online, đúng epoch và đủ mới. Capture/latest slot, safe handover và private decoder ownership được giữ.
- **Đo từng phần:** acquisition, preprocessing, work-lock wait, detection (bao gồm detector-lock/enhancement bên trong), observation/quality, tracking/association, verification bookkeeping, total sample và frame-received-to-result. Lane PAD/FaceID có model dispatch time, pending/busy, queue wait, errors/dropped/stall. Queue wait đo từ submit tới bắt đầu job; không trộn với sensor/network latency.
- **Metadata:** input main/substream, kích thước/seq AI, substream FPS/age, detector/observation counts/errors/recovery và quality/PAD reason codes. Chỉ số hữu hạn, enum allowlist, không trả raw exception/source/token/embedding/image. Giữ auth/camera/store scope hiện có.
- **Overlay:** packet theo đúng camera, watermark epoch/timestamp chống regression, expiry tối đa 1 giây tính cả tuổi kết quả trên server. Packet lặp không gia hạn kết quả cũ. Khi hết hạn xóa box và báo panel chờ dữ liệu mới; không kéo dài Verified bằng animation. Giữ contain/letterboxing, mirror, clipping, resize/fullscreen mapping và cancellation.
- **Ảnh:** current track dùng saved evidence đúng event; recent/dialog dùng finite authenticated API, tối đa ba tải ảnh cùng lúc, bounded retry và abort/revoke object URL khi đổi camera/store/quyền/logout/hide/expiry. Không dùng ảnh history khác để lấp live panel. Không bypass `evidence.view`.
- **Một camera lớn:** trang Nhận diện có một main-quality presentation owner và dropdown toàn bộ registry được cấp quyền. Khởi tạo ưu tiên AI-active; refresh giữ lựa chọn đã chọn. Camera & giám sát vẫn có grid nhiều camera. Đổi camera chỉ retire subscription xem, không start/stop worker, đổi source, reset appearance hay recording.
- Thêm script benchmark GET trong browser đã đăng nhập và script tài nguyên Windows chỉ đọc. Không cần mật khẩu/token/RTSP URL.

Không đổi FaceID/PAD threshold, model, database schema, attendance/counting, #NNNN, authentication/RBAC, installer hoặc sidebar/dashboard. Không tạo nhận diện giả trong Production. Các automated tests dùng dữ liệu/mocks QA tách biệt.

## 3. PARTIAL / BLOCKED

**PARTIAL:** tracking geometry đã cải thiện, overlay freshness và một camera lớn đã có code/tests. Chưa chứng nhận chuyển động/occlusion/identity switch trên người thật, hoặc overlay đồng bộ chính xác với RTP/WebRTC trên máy khách. Không có optical-flow tracker mới giữa các detection; không tuyên bố trải nghiệm tương đương video tham chiếu. Định danh khi hai mặt che nhau/trajectory không phân biệt vẫn cần nghiệm thu và identity revalidation hiện có.

**BLOCKED bởi dữ liệu hardware/browser Production chưa có:** before/after 1/2/4-camera benchmark, CPU/GPU/VRAM/RAM thực tế, active PAD execution provider, model accuracy/false reject trên Hikvision, protected image HTTP/UI thật, fullscreen/video thật và soak. Responsive/focus của bản xem bố cục tĩnh đã PASS ở mục 0; không thay thế các gate Production này. Tool context không nhìn thấy listener port 8100 kể cả một read đã được escalation; **không dùng kết quả này để kết luận Production của người dùng offline**. Không khởi động thêm server/decoder để giả lập nghiệm thu. FaceID code dùng OpenCV CPU path; CPU model-load kiểm tra trước đây không xác nhận execution provider của worker PAD đang chạy.

## 4. Focused tests

| Gate thực sự đã chạy | Kết quả |
|---|---:|
| Public telemetry/scoped API + worker status/race/background admission + appearance | 84 PASS |
| Tracking assignment 5 + acquisition 3 + private capture 22 + async/security lanes 19 + selected v536 contracts 7 | 56 PASS |
| AI registry/source/evidence/handover contracts | 13 PASS |
| Browser media lifecycle/expiry 48 + geometry 7 + overlay labels 4 + recognition controller 18 + recent photos 22 + benchmark privacy 2 | 101 PASS |
| Hai identity-owner/reacquire guard functions hiện có, chạy cô lập khỏi import legacy không còn dùng | 2 PASS |
| Compile source/tests Python; JS syntax; PowerShell parser | 8 Python / 5 JS / 1 PS PASS |
| Camera thật: recognition accuracy, spoof, FPS/latency, simultaneous cameras, continuous soak | BLOCKED / chưa nghiệm thu |

Tổng suite tại checkpoint nhận diện trước thay đổi bố cục: **153 Python + 101 Node PASS**, không cộng lại rerun. Phần UI bổ sung có gate riêng 102 Node PASS ở mục 0. Gate configuration trước scope mới có 21 PASS, file configuration giữ nguyên. Năm regression được tái hiện FAIL trước sửa (hai association, một stale overlay, hai unused-copy), sau sửa PASS.

**FAIL còn ghi nhận trong legacy:** `tests_legacy/test_v15_walkby_liveness_gate.py` có hai ca fixture thiếu sharpness/brightness nên bị quality gate hiện hành chặn; `test_v1_face_best_recognition.py::test_repeated_pad_replay_blocks_before_faceid` kỳ vọng BLOCKED sau bốn observation trong khi policy hiện có cần ít nhất năm cho nhánh đó. Cả ba vẫn FAIL khi dùng association cũ từ checkpoint **chỉ trong bộ nhớ**; không rollback source để đối chiếu. Không hạ security gate hoặc sửa model để làm chúng PASS. Module legacy `test_v1_face_pro_r2.py` không collect nguyên file vì import ClassroomEngine đã không còn; hai guard liên quan đã chạy cô lập và PASS. Cần bảo trì các legacy fixtures riêng trước khi chốt release/commercial acceptance.

Một số lệnh ban đầu thiếu test import path/httpx trong QA venv; đã dùng dependencies có sẵn, không cài mới, và chạy gate phù hợp thành công. Không sửa thư viện pytest đang mở trong IDE. Giữ deprecation warnings hiện có; không refactor lifespan.

## 5. Benchmark trước / sau và giới hạn số liệu

Camera baseline là **một sample do người dùng cung cấp**, không phải benchmark 30 giây. Chưa có after sample với face/input/stage counters. Không báo cải thiện FPS, CPU/GPU hoặc độ chính xác khi chưa đo.

Microbenchmark chỉ ghép geometry, 200 samples mỗi trường hợp cùng tiến trình, không model/camera:

| Số mặt | Greedy cũ median / p95 ms | Global motion mới median / p95 ms |
|---:|---:|---:|
| 2 | .0104 / .0130 | .0201 / .0261 |
| 4 | .0337 / .0458 | .0629 / .0763 |
| 10 | .1463 / .1604 | .3182 / .3291 |

Ghép toàn cục tốn thêm khoảng .17 ms median với 10 mặt trong geometry fixture để tránh hai lỗi đã tái hiện. Đây **không phải** benchmark AI FPS/nhận diện người thật. Chi tiết: `TRACKING_MICROBENCHMARK_20261009.json`. CPU/GPU/RAM Production: **chưa đo**, không điền 0 thay unknown. Decode/sensor/network/event-to-browser end-to-end chưa có trace độc lập; không gọi acquisition time hoặc HTTP round trip là WebRTC latency.

## 6. Files changed trong phần tiếp nối

Không có Git CLI/.git metadata trong workspace để xuất status/diff; đã giữ các thay đổi có trước, không reset/clean/discard. File source/test trực tiếp sửa/tạo:

| Nhóm | Files |
|---|---|
| Camera/AI | `module_app/camera.py`, `module_app/walkby.py`, `module_app/ai_pipeline_v550.py`, `module_app/main.py` |
| Recognition/media | `frontend/js/app.js`, `frontend/js/btmh_recognition_slots.js`, `frontend/js/btmh_recent_recognition.js`, `frontend/js/btmh_media_v5410.js`, `frontend/index.html`, `frontend/css/btmh_recognition_slots.css`, `frontend/css/btmh_recognition_console.css` |
| Scripts | `scripts/benchmark_camera_ai.js`, `scripts/measure_camera_ai_host.ps1`; readonly diagnostic trước đó giữ nguyên |
| Python tests | `tests_demo/test_ai_diagnosis_contract.py`, `tests_v54/test_ai_pipeline_v550.py`, `tests_v54/test_tracking_assignment_v5410.py`, `tests_v54/test_ai_acquisition_v5410.py` |
| Node tests | `tests_browser/recognition_slots.test.cjs`, `tests_browser/recent_recognition.test.cjs`, `tests_browser/media_lifecycle.test.cjs`, `tests_browser/media_overlay.test.cjs`, `tests_browser/media_overlay_labels.test.cjs`, `tests_browser/camera_ai_benchmark.test.cjs`, `tests_browser/visual_recognition_console.cjs` |
| Docs | `PRODUCT.md`, `DESIGN.md`, camera diagnosis ExecPlan/report follow-up, realtime ExecPlan/report/checkpoint, safe follow-up evidence JSON, microbenchmark JSON |

QA data roots `.qa_camera_ai_followup_20261009*` độc lập, không ship; không dùng customer data để chạy tests. Source checkpoint archive hiện có được đọc để đối chiếu, không khôi phục hoặc sửa nó.

## 7. Khởi động và chẩn đoán Windows

Nạp backend source mới bằng launcher hiện có. Dừng tiến trình đang chạy bằng Ctrl+C trong terminal của nó trước khi khởi động lại; không chạy hai server. Codex chưa restart Production:

```powershell
Set-Location 'C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM'
.\START_CAMPUSFACE.bat
```

Mở `http://127.0.0.1:8100/`, **Ctrl+F5**, chọn Hikvision. AI cấu hình vẫn do người quản lý lưu riêng cho từng camera đúng cửa hàng/khu vực; không cần bật Laptop để Hikvision chạy.

Chẩn đoán configuration/model files chỉ đọc (CMD dùng cùng Python path và `cd /d`):

```powershell
& "$env:LOCALAPPDATA\CampusFace\runtime\venv\Scripts\python.exe" -B .\scripts\diagnose_camera_ai.py
```

Trong browser đã đăng nhập, GET `/api/v1/media/metadata?camera_id=2` khi mặt thẳng/rõ vẫn ở trong hình. Cần `ai_detection`, `ai_performance.stage_times`, PAD/FaceID counters và quality reason của tracks. Không gửi tên/mã người, ảnh/token/cookie/source. `detected_faces=0` nhiều samples là detector/input branch; detected>0/observed=0 là observation branch; tracks có quality wait là gate trước verification; PAD completed tăng/blocked là nhánh PAD; PAD PASS/FaceID completed tăng nhưng chưa recognized mới kiểm tra matching/enrollment scope. Không suy ra những trường hợp đó chỉ từ một empty sample.

Đo tài nguyên host trong **Terminal Windows của người dùng**, không đổi ExecutionPolicy hay security settings:

```powershell
& ([scriptblock]::Create((Get-Content -LiteralPath .\scripts\measure_camera_ai_host.ps1 -Raw))) -Seconds 30
```

Script tìm PID listener và đo nó/các tiến trình con; không đọc command line. Nếu CIM/TCP không cho tìm PID, thêm `-BackendProcessId <PID backend đang chạy>` lấy từ Task Manager; không đo nhầm tiến trình QA. GPU được ghi NOT_MEASURED; đối chiếu Task Manager GPU Compute/VRAM, không coi GPU của browser là GPU inference.

Đo API/camera/browser: mở file `scripts/benchmark_camera_ai.js`, copy nội dung vào DevTools Console của chính trang BTMH đã đăng nhập. Không dán cookie/token. Script chỉ khai báo hàm; gọi:

```javascript
await BTMHCameraAIBenchmark({cameraIds:[2], seconds:30})
```

Với hai camera được **người dùng** cấu hình AI, gọi `cameraIds:[1,2]`. Với bốn camera chỉ đo khi cả bốn thiết bị thật/AI có cấu hình hợp lệ. Script không tự bật camera, không tạo worker/event, không nhúng ảnh/danh tính. Giữ vị trí người, ánh sáng, camera settings, máy và thời lượng giống nhau để so sánh. Browser FPS chỉ có cho camera đang được xem; camera nền vẫn đo qua metadata. HTTP round trip gồm API work; `videoLatencyMs=null` vẫn là chưa đo.

## 8. Checklist nghiệm thu / còn thiếu để chốt thương mại

1. Laptop và Hikvision LIVE trên nguồn thật; thử Hikvision-only trước, rồi hai AI-active. Xác minh actual AI input main/substream/size/freshness, không chỉ nhìn video LIVE.
2. Một người đi liên tục/quay đầu trong giới hạn nhìn thấy; nhiều người, hai người đi ngang nhau/che nhau; đo ID switch/mất track và latency. Test geometry PASS chưa thay phép đo này.
3. PAD/model thật phân biệt người thật và ảnh/video spoof, fail-closed khi error/timeout; nhân viên đã enrollment/phê duyệt nhận đúng tên. Đo thời gian tới Verified và false reject của Hikvision; không giảm threshold để đạt KPI.
4. Khi Unknown → Verified giữ #NNNN; rời/re-enter mới là appearance mới theo policy. Đứng liên tục không trùng recognition/attendance. Kiểm tra history đúng camera/store/timezone; cần nghiệm thu qua thời điểm reset ngày.
5. Panel/ảnh/recents: chọn đúng camera, classified event có ảnh thật khi đủ quyền. ANALYZING chưa lưu ảnh hiển thị placeholder đúng; 403/404 báo đúng. Đổi camera/hide/logout/metadata expiry không khôi phục ảnh hoặc tên cũ.
6. Resize/fullscreen/aspect ratio khác nhau: box đúng vị trí; không hai lớp overlay. Ngắt metadata để xác minh box/tên cũ hết hạn dù video còn chạy. WebRTC latency cần phép đo browser thật.
7. Đổi camera/đổi trang/ẩn tab: chỉ subscription xem nghỉ; các camera AI-active khác tiếp tục tạo event thật. Không reset appearance, recording hoặc duplicate worker/recognition.
8. Reconnect/shutdown/soak 1/2/4 camera trên phần cứng phù hợp: ghi CPU/GPU/RAM growth, FPS, stage/queue times, dropped/stalled/errors, duplicate count và chất lượng nhận diện. Không tự cam kết FPS cố định cho mọi máy.

Phần thiếu quyết định hiện tại: **samples Hikvision mới có mặt + detection/stage counters, protected image HTTP/UI, benchmark trước/sau trên host, nghiệm thu người thật/spoof/crossing và continuous soak**. Không đóng dấu Production/commercial PASS từ automated tests. Dừng sau báo cáo theo yêu cầu.
