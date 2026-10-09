# BTMH V5.4.10 — Authentication, Production và offline deployment

Ngày: 2026-10-09. Source chính: `PROJECT/BTMH_SYSTEM/`.

**Trạng thái: PARTIAL / BLOCKED — chưa PRODUCTION READY, chưa có bộ cài hoàn chỉnh để giao khách hàng.** Các regression xác định được đã sửa và kiểm thử. Payload PostgreSQL, hồ sơ phân phối bắt buộc và nghiệm thu Production trên môi trường thật còn thiếu. Không thay database khách hàng bằng SQLite/Preview để vượt kiểm tra.

## 1. DONE

- Đọc hướng dẫn, PRODUCT/DESIGN, MASTER/checkpoint/report hiện có; giữ source hiện tại. Không rollback, reset, clean, discard, thay schema hoặc thay ngưỡng nhận diện.
- Tách rõ Login, Đăng ký qua invitation/QR và First Owner setup. Login là màn hình mặc định; thông báo/nút khởi tạo chỉ xuất hiện theo trạng thái server.
- Bootstrap Owner kiểm tra và tạo trong một transaction; ngăn hai yêu cầu đồng thời tạo hai Owner. Owner/Admin bị vô hiệu hóa vẫn được tính là hệ thống đã thiết lập.
- Sửa launcher Production: chặn inherited Preview trước mọi mutation, xử lý đúng return code PostgreSQL, yêu cầu PostgreSQL/background camera/PAD/FFmpeg/MediaMTX, báo URL và mở trình duyệt sau startup/bind thành công. Không in RTSP credentials.
- Hoàn thiện pipeline offline với kiểm tra artifact/provenance/hash/license, direct pins/transitive closure, manifest trước khi chạy Python installer, `--no-index`, chặn dependency URL từ wheel, stage sạch và từ chối upgrade khi runtime còn chạy.
- Tải/xác minh MediaMTX, Python installer, ba model và 60 wheels trên máy build; chạy các focused tests và kiểm tra runtime thực tế ở data root QA riêng.

## 2. PARTIAL

Launcher và script đóng gói đã hoàn thiện trong phạm vi lỗi xác định, nhưng chưa chạy một phiên Production đầy đủ với PostgreSQL và camera thật. ZIP/EXE chỉ được build khi audit thành công; payload hiện tại chưa đạt. UI đã qua kiểm tra routing/API/assets; nghiệm thu hình ảnh, responsive và keyboard/focus trong browser thật chưa chạy vì môi trường CUA hiện không có browser/app.

Các chức năng MASTER — bốn camera slots, multi-person boxes, appearance ID, Unknown → Verified, dedup, background AI, history, attendance, counting, PAD và QR approval — giữ implementation đã chốt. Không triển khai lại và không lấy kết quả checkpoint cũ làm PASS mới.

## 3. BLOCKED

- Thiếu `vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip`, digest/provenance độc lập và sidecar `.zip.sha256` khớp. Không tự tạo checksum rồi gọi đó là bằng chứng upstream.
- Hồ sơ phân phối chưa hoàn tất: review records cho các component, PostgreSQL license/bundled notices, FFmpeg GPL/build/corresponding-source evidence; notices thiếu trong wheels dnspython và flatbuffers.
- Chưa có máy Windows sạch để nghiệm thu cài offline/upgrade/backup restore; chưa có PostgreSQL thực tế trong test này.
- Chưa nghiệm thu camera RTSP/WebRTC, người thật/spoof, GPU/soak, điện thoại và LAN HTTPS đáng tin cậy.

Chi tiết từng lỗi: [audit payload](OFFLINE_PAYLOAD_AUDIT_20261009.json), [audit phân phối](THIRD_PARTY_DISTRIBUTION_AUDIT_20261009.md).

## 4. Files changed

Không có Git CLI và `.git` metadata trong workspace nên không xuất được git status/diff. Danh sách dưới đây ghi file trực tiếp sửa/tạo trong nhiệm vụ; không xác nhận trạng thái commit hay các thay đổi có trước.

| Nhóm | File tương đối trong source chính |
|---|---|
| Auth/backend | `module_app/auth.py` |
| Auth/frontend | `frontend/index.html`, `frontend/js/app.js`, `frontend/css/btmh_auth_ui_v550.css` |
| Auth/media regression | `tests_browser/auth_routing.test.cjs`, `tests_browser/media_lifecycle.test.cjs`, `tests_demo/test_auth_bootstrap_regression.py`, `tests_v54/test_auth_routing_regression.py` |
| Production startup | `START_CAMPUSFACE.bat`, `run_module.py`, `scripts/check_ready.py` |
| Startup regression | `tests_v54/test_mediamtx_launcher.py`, `tests_v54/test_production_launch_readiness.py` |
| Customer setup | `INSTALL_CURRENT_PC_WINDOWS.bat`, `INSTALL_CAMPUSFACE_V1_WINDOWS.bat` |
| Build/acquisition wrappers | `PREPARE_PORTABLE_OFFLINE_WINDOWS.bat`, `PREPARE_POSTGRESQL_OFFLINE_WINDOWS.bat`, `BUILD_FULL_OFFLINE_PACKAGE_WINDOWS.bat`, `BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat`, `BUILD_SETUP_EXE_WINDOWS.bat`, `CHECK_OFFLINE_PACKAGE_WINDOWS.bat` |
| Offline audit/staging | `scripts/validate_portable_bundle.py`, `scripts/package_offline_bundle.py`, `scripts/verify_offline_bundle.ps1`, `scripts/assert_install_stopped.ps1`, `tests_v54/test_offline_bundle_audit.py` |
| Runtime setup | `scripts/prepare_core_models.py`, `scripts/runtime_quick_check.py`, `scripts/setup_embedded_postgres.ps1` |
| Installer | `installer/CampusFace-V1.13.iss` |
| Payload instructions/provenance | `OFFLINE_DEPLOYMENT.md`, `vendor/README.txt`, `vendor/offline-provenance.json`, `models/README.txt` |
| Plan/report/evidence | `docs/EXECPLAN_AUTH_PRODUCTION_OFFLINE_20261009.md`, `docs/THIRD_PARTY_DISTRIBUTION_AUDIT_20261009.md`, `docs/PRODUCTION_RUNTIME_EVIDENCE_20261009.json`, `docs/OFFLINE_PAYLOAD_AUDIT_20261009.json`, báo cáo này |
| Acquired payload | Python EXE, MediaMTX ZIP, ba `.onnx` model và `vendor/wheels/*.whl` (60 file), vị trí/hash ở mục 7 |
| Retained license/acquisition files | `vendor/licenses/{python,mediamtx,yunet,sface,pad}/{LICENSE.txt,ACQUISITION.txt}` |
| QA riêng, không ship | `.qa_production/{acquire_artifacts.py,install_offline_runtime.py,verify_model_runtime.py,artifact-acquisition.json,model-runtime-results.json}`; offline venv/model/media test roots và isolated test scratch |

Không sửa file pytest đang mở trong IDE, thư mục index đầu workspace hoặc core FaceID/PAD/video/attendance/counting.

## 5. Test results — PASS / FAIL / NOT RUN

| Kiểm tra mới chạy | Kết quả | Giới hạn bằng chứng |
|---|---:|---|
| Auth routing/QR ASGI | 9 PASS | API thật, private SQLite, TestClient; không phải PostgreSQL |
| Bootstrap/service/concurrency | 7 PASS | SQLite concurrent connections thật; PostgreSQL mới kiểm tra SQL-lock adapter |
| SMS/MFA regression hiện có | 42 PASS | Không kiểm chứng SMS delivery nhà cung cấp |
| Node auth routing/account | 11 + 10 PASS | Routing/session UI logic |
| Node mobile/QR admin/desktop enrollment | 22 + 25 + 13 PASS | Giữ luồng invitation và approval; không phải phone camera |
| Node media lifecycle | 45 PASS | Mount/main-small/fallback/fullscreen/cleanup logic |
| Production startup/readiness | 16 PASS | Batch thật trong fixture tách biệt; service/server collaborators cho policy/order |
| MediaMTX launcher + offline importer suites | 25 PASS | Kiểm tra control flow/provenance/rejection; không phải live video |
| Offline packaging suite | 16 PASS | Tampering, extra wheel, static mapping, secret exclusion, active interpreter refusal, chặn remote dependency |
| Python compile / JS syntax / PowerShell parse | PASS | 12 Python source/test, 3 JS files và 3 PowerShell packaging scripts; 3 JSON evidence files parse thành công |
| MediaMTX ZIP import + discovery + executable version | PASS | Binary thật trả `v1.21.1`, tại `.qa_production/media-runtime` |
| Cài 60 wheels `--no-index` + `pip check` | PASS | Venv QA bằng Python 3.12.10 có sẵn; chưa chạy EXE trên máy sạch |
| YuNet/SFace load + PAD ONNX Runtime probe | PASS | Models thật; không kết luận độ chính xác người/spoof |
| FFmpeg resolution + `-version` | PASS | Binary thật 7.1, GPL/version3/static build |
| Localhost HTTP smoke, exact offline-installed runtime | 8 PASS | 3 pages/36 assets, auth/session/RBAC/QR API; isolated preview test profile cấm hardware/external network |
| Audit payload thực tế | BLOCKED | Dependency closure PASS; 60 wheels, 5 verified artifacts, 14 missing-evidence issues |
| Build pipeline thực tế | BLOCKED đúng thiết kế | Native exit 2; kiểm tra không tạo stage hay ZIP |
| Inno EXE compilation / clean Windows / operational Production | NOT RUN | Payload gate chưa đạt |
| Camera/GPU/phone/LAN HTTPS/PostgreSQL thật | NOT RUN | Không có acceptance evidence |
| Full `tests_v54` / `VERIFY_RELEASE.py` rerun | NOT RUN | Theo scope focused tests, không lặp hàng trăm MASTER checks chưa đổi |

Không còn FAIL trong các focused suite đã hoàn thành. Ban đầu media suite có một assertion đòi nhãn kỹ thuật cũ; đã sửa fixture theo nhãn LIVE hiện hành và chạy lại đạt 45 PASS, không đổi product media code. Một số lần chạy bị WinError5 của sandbox; các lần approval của agent bị hủy không được tính là đã chạy. Các lần root thực sự chạy sau escalation đạt kết quả nêu trên.

Lệnh kiểm tra chính:

```powershell
$env:CAMPUSFACE_DATA_ROOT = Join-Path (Get-Location) '.pytest_report_qa_20261009'
$env:CAMPUSFACE_DB_MODE = 'sqlite'
$env:PYTHONDONTWRITEBYTECODE = '1'
& '.qa_production\offline-venv\Scripts\python.exe' -B tests_v54/test_production_launch_readiness.py -v
& '.qa_production\offline-venv\Scripts\python.exe' -B tests_v54/test_offline_bundle_audit.py -v
& '..\..\.test_venv\Scripts\python.exe' -m pytest -q -o addopts= tests_v54/test_mediamtx_launcher.py tests_v54/test_mediamtx_offline_installer.py
& '.qa_production\offline-venv\Scripts\python.exe' -B scripts/validate_portable_bundle.py --report docs/OFFLINE_PAYLOAD_AUDIT_20261009.json
```

Các test dùng environment/data roots riêng; không chạy lệnh test against database Production. Evidence tổng hợp: [runtime evidence](PRODUCTION_RUNTIME_EVIDENCE_20261009.json).

## 6. Xác nhận Login và Registration

**PASS ở mức routing/API/session đã kiểm thử.** Tài khoản hiện có đăng nhập bằng username/password, xử lý sai thông tin, logout rồi login lại; MFA và RBAC/store scope giữ server authority. Trạng thái database trống không thay thế Login.

Đăng ký mở luồng employee enrollment bằng QR/invitation token hợp lệ trên cùng origin; không giữ token trong browser storage, không cấp Owner/Admin công khai. Luồng PENDING → APPROVE/REJECT/REQUEST REENROLLMENT được giữ. Link QR có dạng `/enroll#invite=<token>`, không có một public privileged-signup API mới.

First Owner setup chỉ khả dụng khi server xác nhận chưa có Owner/Admin, vẫn qua quy trình bootstrap an toàn hiện có. Atomic transaction ngăn tạo Owner thứ hai; conflict refresh trạng thái server. Khi đã thiết lập, không quay về setup; tài khoản bị disable không mở lại bootstrap. Nghiệm thu form/render/responsive trên browser thật và auth concurrency PostgreSQL thật còn NOT RUN.

## 7. Các thành phần payload đã chuẩn bị

**Đã có artifact tại source, chưa đóng thành ZIP/EXE release.**

| Component | Vị trí | SHA256 |
|---|---|---|
| Python 3.12.10 amd64 | `vendor/python-3.12.10-amd64.exe` | `67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb` |
| MediaMTX 1.21.1 amd64 | `vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip` | `faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23` |
| YuNet | `models/face_detection_yunet_2023mar.onnx` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| SFace | `models/face_recognition_sface_2021dec.onnx` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |
| Passive PAD | `models/minifasnet_v2.onnx` | `b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907` |
| Backend/inference/media packages | `vendor/wheels/*.whl`, 60 wheels | Mỗi hash/version/dependency/notice ở audit JSON |
| FFmpeg | Embedded executable trong `imageio-ffmpeg==0.6.0` Windows wheel | Hash wheel ở audit; binary đã thực thi version |
| Backend/frontend/config/setup | Source release whitelist + per-file manifest khi build đạt | Stage loại QA/secrets/database/logs/backup/venv |

Python publisher signature thực tế là Valid/Python Software Foundation. Các URL nguồn và verification method nằm trong [provenance](../vendor/offline-provenance.json). ZIP MediaMTX nhỏ/hỏng trong `.test_media` đã bị từ chối, không chạy hoặc dùng thay payload thật.

## 8. Binary/dependency/evidence còn thiếu

PostgreSQL archive và upstream acquisition evidence/sidecar là dependency runtime còn thiếu. Các Python dependency đã resolve và cài offline đủ trong QA; không đồng nghĩa hoàn tất installer.

Chưa có review records và notices đầy đủ như audit yêu cầu. FFmpeg thực tế bật `--enable-gpl --enable-version3 --enable-static`; wrapper BSD license không đủ cho binary. Không có exact corresponding-source/build evidence và license/notice bundle hoàn chỉnh để phát hành. Wheels dnspython 2.9.0 và flatbuffers 25.12.19 thiếu retained notice files. Không repack wheel hay tạo hồ sơ giả để làm audit PASS.

## 9. Production launch command

Sau khi cài đầy đủ dependency đã xác minh, từ terminal bình thường dưới đúng standard Windows user:

```powershell
Set-Location 'C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM'
.\START_CAMPUSFACE.bat
```

Trên máy khách, đổi path thành thư mục chương trình đã cài. Launcher mặc định Production dù shell thừa kế development env. Nếu inherited `BTMH_UI_PREVIEW=1`, launcher dừng trước mutation; mở terminal bình thường. Không dùng `START_BTMH_UI_PREVIEW.bat` làm sản phẩm, không bỏ gate hoặc vô hiệu hóa PAD/camera/AI. Hiện chưa xác nhận một Production server vận hành đầy đủ bằng lệnh này.

## 10. Website URL

Mặc định **`http://127.0.0.1:8100/`**, sau startup thành công. `MODULE_HOST`/`MODULE_PORT` đã cấu hình có thể đổi URL; dòng `[WEB_READY]` sau lifespan và bind mới là thông báo backend đã khởi động. Nó không tuyên bố mọi camera/AI/recording đã operational. Port 8810 thuộc Preview.

Điện thoại/LAN cần origin truy cập được và HTTPS certificate đáng tin cậy theo chính sách hiện có; chưa có URL LAN đã nghiệm thu trong nhiệm vụ này.

## 11. Quy trình cài offline trên Windows

Chỉ áp dụng cho release **đã vượt audit**, hiện chưa có release đó. Hướng dẫn đầy đủ: [OFFLINE_DEPLOYMENT](../OFFLINE_DEPLOYMENT.md).

1. Máy build hoàn thiện PostgreSQL/provenance/hash và hồ sơ phân phối; chạy `CHECK_OFFLINE_PACKAGE_WINDOWS.bat`. Không bỏ qua lỗi.
2. Audit PASS mới chạy `BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat` hoặc `BUILD_SETUP_EXE_WINDOWS.bat` với Inno Setup 6 trên máy build. Chuyển release/checksum đã xác minh bằng USB hoặc kênh phát hành.
3. Máy khách Windows x64 nhận ZIP/EXE; dùng standard user, không Run as administrator. ZIP giải nén vào thư mục chương trình mới; EXE sử dụng thư mục chương trình riêng của user.
4. Trước repair/upgrade, backup bằng workflow hiện có, Ctrl+C dừng backend và chạy `STOP_POSTGRESQL_WINDOWS.bat`. Guard từ chối runtime còn chạy, không tự kill hay reset data. Bản cũ có bytecode/extra code phải dùng thư mục code sạch; không nới manifest gate.
5. ZIP chạy `SETUP_OFFLINE_WINDOWS.bat`; EXE gọi setup offline sau copy. Manifest/hash/publisher được kiểm tra trước installer; Python/wheels/FFmpeg/models/MediaMTX/PostgreSQL lấy từ payload local. Không fallback Internet.
6. Giữ data root đã resolve: mặc định `%LOCALAPPDATA%\CampusFace`, hoặc legacy/configured root hiện có. Không xóa account/database/biometric/credentials. Chạy Production launcher rồi bootstrap Owner đầu tiên nếu server cho phép; không ship mật khẩu mặc định.
7. Nghiệm thu restart/shutdown/logs/backup restore cùng phần cứng/network thật. Runtime dùng process supervisor per-user hiện có; không tuyên bố đã cài Windows service mới.

Logging dưới data root `logs/`. Uninstaller metadata được đặt ngoài code payload; setup/launch không tạo bytecode vào nguồn đã manifest. Rollback code dùng bản chương trình trước và data root cũ đã bảo toàn, không phục hồi database đang live để rollback source.

## 12. Chức năng đã kiểm chứng thực tế

Đã thực thi binary MediaMTX đúng version; cài offline 60 packages; tải model thật YuNet/SFace và PAD ONNX Runtime probe; thực thi FFmpeg; chạy HTTP localhost với backend/auth/session/RBAC/QR API và static assets; chạy batch Windows trong fixture tách biệt; guard upgrade từ chối interpreter đang sống mà không kill; audit và build thực tế từ chối payload thiếu, không tạo output.

Các HTTP tests dùng database SQLite và preview **test profile** để cô lập phần cứng. Đây là evidence tích hợp API/assets/auth, không thay thế Production PostgreSQL/camera. Không chạy Python EXE cài vào máy sạch, không sửa data root vận hành, không tuyên bố WebRTC/person/spoof/GPU đã PASS.

## 13. Nghiệm thu còn bắt buộc

| Nhóm | Cần nghiệm thu thật |
|---|---|
| Windows/deployment | Network disabled; clean install EXE/ZIP, standard-user permissions/cert chain, restart/shutdown, upgrade giữ account/keys/camera/data, backup/restore, rollback code, logs/resource cleanup |
| PostgreSQL | Actual version/runtime/startup, safe migration, bootstrap concurrency, attendance transactions/duplicate prevention, credential protection, backup/restore |
| Website | Browser render/brand/responsive/forms/focus/navigation/error handling; production login/MFA/enrollment/store scope |
| Camera/media | RTSP connect, decoded WebRTC, 4 slots, reconnect, handover, cleanup, recording, background AI không lệ thuộc UI |
| Recognition | Multiple persons/boxes/labels, appearance #NNNN theo camera/ngày, Unknown → Verified giữ ID, dedup/history/counting/attendance đúng nghiệp vụ |
| FaceID/PAD/GPU | Người thật, ảnh/video spoof, fail-closed/timeout/errors, GPU/resource/soak; không chấp nhận người chưa đủ điều kiện |
| Phone/QR/HTTPS | Reachable trusted HTTPS, token, camera capture/FaceID/PAD, PENDING, approve/reject/request reenrollment, hết hạn/reuse prevention |

## 14. Các vấn đề chặn phát hành thương mại

Payload PostgreSQL chưa đủ; audit phân phối/notices/source chưa đạt; chưa có installer đã build và nghiệm thu offline trên Windows sạch; chưa có Production PostgreSQL/camera/WebRTC/recognition/PAD/GPU/phone/HTTPS acceptance. Đó là các release blockers hiện tại. Source fixes và isolated test PASS không xóa các blockers này.

Mọi phần độc lập trong phạm vi regression/startup/packaging đã hoàn tất. Không phát hành ZIP/EXE hoặc tuyên bố PRODUCTION READY. Dừng sau báo cáo này theo yêu cầu.
