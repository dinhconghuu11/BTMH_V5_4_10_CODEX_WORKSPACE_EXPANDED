# Nghiệm thu Windows, WebRTC và Hikvision thật — BTMH 5.5.0

Ngày cập nhật: 2026-10-07. Đây là quy trình nghiệm thu chưa chạy, không phải kết quả phần cứng. Test giả lập, kiểm tra source/cú pháp và release verifier được ghi riêng trong [QA_V550.md](QA_V550.md); chúng không chứng minh FPS, độ trễ, model/GPU, PostgreSQL hay giao diện đã render trên máy thật.

## 1. Điều kiện và dữ liệu được bảo vệ

- Dùng Windows, browser và camera thử nghiệm đã được cấp quyền; ghi model/firmware, browser/version, cấu hình main/small, CPU/GPU/RAM và kiểu kết nối LAN. Dùng bản runtime/MediaMTX đã có và được xác minh; nếu thiếu binary hoặc môi trường thì ghi **BLOCKED**, không tải thêm hoặc tạo installer trong đợt nghiệm thu này.
- Camera record trong database là nguồn chuẩn. Dùng công cụ cấu hình hiện có, không hard-code IP/password và không đưa RTSP URL chứa credentials vào browser storage, Console, ảnh, log hoặc báo cáo. Không lưu Authorization headers, token hoặc session URL trong bằng chứng.
- Giữ cấu hình main `/Streaming/Channels/101` đang vận hành; không hạ độ phân giải/FPS hoặc thay threshold để đạt số đo. H.264 1920×1080, 25 FPS chỉ là baseline nếu camera hiện dùng cấu hình đó. Ghi codec thực tế từ status, không suy ra codec từ tên camera.
- Giữ FaceID, Passive PAD, anti-spoof, multi-frame gates, attendance, RBAC và recorder hoạt động. Một camera/substream không tương thích phải báo fallback rõ ràng; không tắt security để tăng FPS.
- Xác định DataRoot từ dòng `Data:` trên launcher. `CAMPUSFACE_DATA_ROOT` được ưu tiên; profile mặc định có thể là `%LOCALAPPDATA%\CampusFace` hoặc profile cũ `%LOCALAPPDATA%\CampusFaceV1142`. Không tạo profile khác để thay thế dữ liệu đang vận hành. Các bài offline/PostgreSQL bên dưới dùng DataRoot/database thử nghiệm riêng, không dùng database khách hàng.

Local và LAN được nghiệm thu riêng qua launcher hiện có. Browser LAN truy cập PC BTMH, không truy cập trực tiếp camera/MediaMTX. Cho phép cổng ứng dụng thực tế và ICE trên mạng Private; mặc định ứng dụng TCP 8100, ICE UDP/TCP 8189, nhưng dùng `ice_port` từ status nếu cấu hình khác. WHEP 8889, API 9997, metrics 9998 và relay RTSP 8554 giữ loopback. Nếu cần ICE host, cấu hình địa chỉ của PC BTMH bằng công cụ hiện có, không dùng địa chỉ camera.

## 2. Quan sát đúng nguồn và đúng số đo

Trong tab đã đăng nhập với `camera.live`, dùng Console để đọc dữ liệu đã lọc:

```javascript
BTMHMedia.stats()
await api('/api/v1/media/gateway/status')
await BTMHMedia.capabilities(true)
```

`api()` dùng phiên đăng nhập hiện có; không lấy hoặc in token. Mở **Hệ thống → Chi tiết kỹ thuật** bằng tài khoản có `system.diagnostics` để đọc AI/PAD/resources. Khi đóng chi tiết hoặc ẩn trang, phần diagnostics phải ngừng polling và không mở camera/model mới.

| Số đo/trạng thái | Cách nghiệm thu |
| --- | --- |
| `transport` | Native đạt kiến trúc khi là `NATIVE_GATEWAY_WEBRTC` và có hình mới; process/signaling ready chưa đủ. |
| `requestedQuality`, `quality`, `qualityFallbackReason` | Phân biệt chất lượng yêu cầu và chất lượng thực tế. Yêu cầu small có thể thực tế main; lý do quality fallback phải rõ, độc lập với transport fallback. |
| `small_available`, `small_fallback_reason` | Khả năng small được backend xác nhận; không coi path đã cấu hình là bằng chứng stream đã decode. |
| `receivedFps`, `decodedFps`, `renderedFps` | FPS nhận/giải mã/trình bày của browser. Dùng **renderedFps** cho mục tiêu video; không thay bằng AI/capture FPS. |
| `videoLatencyMs`, `frameAgeMs`, `frameAgeSource` | `null` là chưa đo được, không phải 0. Tuổi frame fallback không chứng minh độ trễ toàn tuyến native. |
| `playoutBufferMs`, `jitterMs`, `roundTripMs` | Buffer/jitter/RTT, không phải độ trễ camera → màn hình. |
| `source_state`, `source_healthy`, `source_codecs`, lỗi đã lọc | Khi có reader, kiểm tra nguồn đúng, decoded image và codec. `IDLE`/health `null` có thể bình thường khi không còn reader. |
| `app_session_count`, `pending_session_count`, `webrtc_session_count`, `webrtc_connected_count` | Số phiên ổn định theo vùng đang xem; pending về 0 sau khi kết nối/cleanup. Recorder/AI không phải phiên browser. |
| AI capture, AI FaceID/PAD và resources | Đọc mode, tuổi frame, FPS riêng, queue/pending/drop/latency và CPU/RAM. Detector/tracker stage hoặc GPU chưa đo được vẫn là `null`/không rõ. |

Main active đi theo `/101 → MediaMTX → WHEP qua API BTMH → browser video`. AI ưu tiên `/102` chỉ khi được suy ra từ record hợp lệ và chứng minh bằng frame decoded còn mới; khi không có thì báo `MAIN_FALLBACK`. Grid nhiều ô có thể yêu cầu small từ nguồn đã chứng minh đó. Single view/fullscreen, recording và bằng chứng main vẫn dùng main. Recorder ưu tiên relay main `btmhmain`, stream copy; fallback trực tiếp phải báo trạng thái/lý do.

Gateway native hiện phục vụ camera active. Camera khác phải giữ camera scope và báo `NON_PRIMARY_CAMERA` nếu chuyển sang đường fallback của chính camera đó; tuyệt đối không hiện nhầm hình camera active. Chuỗi transport của camera active là native → Python WebRTC → JPEG WebSocket → MJPEG → polling; fallback đang có hình không được ghi PASS cho native.

## 3. Ma trận nghiệm thu camera thật

Mỗi hàng ghi thời gian, camera ID thử nghiệm, transport/quality thực tế, kết quả, bằng chứng đã lọc và người thực hiện. Tất cả hàng dưới đây hiện **BLOCKED** vì chưa chạy trên hardware.

| ID | Bước thực hiện | Điều kiện đạt | Hiện tại |
| --- | --- | --- | --- |
| H01 Main | Chọn camera Hikvision active đã lưu; mở single/Live View. Xác nhận frame mới, codec và stats. | Native đúng camera, `requestedQuality=main`, `quality=main`; recorder vẫn main/copy. | BLOCKED |
| H02 Small | Dùng camera có `/102` decoded còn mới; mở grid 2/3/4 cột. Đổi tên/zone, quan sát thay đổi online/recording rồi đổi 2 → 3 cột. | Ô active yêu cầu small, thực tế small khi hỗ trợ; metadata và bố cục small không tạo lại peer/session; recorder/main evidence không đổi. | BLOCKED |
| H03 Không có small | Dùng camera thử nghiệm có `/102` không khả dụng hoặc codec small bị từ chối; `/101` vẫn hoạt động. Mở grid và chờ bounded fallback. | Yêu cầu small nhưng thực tế main native, có `qualityFallbackReason`; thử small thất bại được cleanup trước main, không negotiation/peer/timer trùng. Không đổi main settings. | BLOCKED |
| H04 Fullscreen | Từ ô small hoặc main fallback mở modal/phóng to; đóng modal; chuyển grid một cột. | Modal/single luôn yêu cầu và phát main. Owner ô được retire trước modal; đóng modal phục hồi đúng camera/quality; không downgrade main thành small. | BLOCKED |
| H05 AI/PAD độc lập | Trong H01–H04 để detector/tracker, FaceID và Passive PAD xử lý bằng model thật; quan sát diagnostics. Dùng bài liveness/anti-spoof hiện có trên dữ liệu thử nghiệm được phép. | Video tiếp tục khi FaceID/PAD bận; mỗi lane tối đa một batch chờ; nguồn/track cũ không ghi nhận identity/attendance sau handover. Policy/threshold/PAD giữ nguyên, bài security hiện có vẫn đạt. | BLOCKED |
| H06 FPS/độ trễ/soak | Chạy protocol mục 4 riêng local và LAN, ít nhất 5 phút mỗi trường hợp đang nghiệm thu. | Rendered FPS ≥15 khi hardware hỗ trợ, mục tiêu camera → màn hình LAN <300 ms; không tích lũy trễ, số owner/RAM không tăng liên tục sau warm-up. | BLOCKED |
| H07 Mất mạng/reconnect | Trên camera thử nghiệm ngắt rồi nối mạng; riêng thử mất small trong khi main còn sống. Ghi thời điểm ngắt/phục hồi và thời gian có frame mới. | Trạng thái/fallback rõ; frame cũ không phát vô hạn; reconnect có backoff, phục hồi đúng nguồn và không có decoder/peer thay thế trước khi owner cũ đã retire. | BLOCKED |
| H08 Registry/lifecycle | Chuyển module khoảng 20 lần, mở/đóng modal, hide/show tab, pagehide/pageshow, logout/login; sửa/disable/delete camera thử nghiệm bằng UI hiện có trong khi request đang chờ. | Kết quả cũ không hồi sinh nguồn/ô/modal; camera khác không bị nhận nhầm; chỉ một transport mỗi slot; polling hidden dừng và reader/session cũ được cleanup. | BLOCKED |

Nếu chưa có camera/model/browser tương ứng, giữ **BLOCKED** và nêu thiếu điều kiện. Nếu đã chạy và không đạt, ghi **FAIL** cùng số đo/lỗi; không đổi mục tiêu hoặc dùng test giả lập để ghi PASS.

## 4. Protocol đo FPS, độ trễ và soak

1. Warm-up đến khi có hình native mới và pending session về 0; ghi thời điểm bắt đầu, độ phân giải/codec thực tế, camera ID, transport/quality. Giữ FaceID/PAD và recorder chạy trong toàn bài.
2. Bắt đầu **5 phút liên tục** cho từng cấu hình main/small/fallback đang nghiệm thu; local và LAN ghi riêng. Lấy stats đã lọc mỗi 10 giây và CPU/RAM/session đầu–giữa–cuối. Ghi received/decoded/rendered FPS riêng, reconnect/fallback, frame freeze và thời điểm khôi phục; không bỏ mẫu xấu. Báo min/median/p95/max và khoảng không có số đo. Mục tiêu rendered FPS giữ **≥15**, không dùng FPS AI thay thế; nếu browser không cung cấp rendered FPS thì hạng mục này **BLOCKED**.
3. Đặt đồng hồ mili giây trước camera. Dùng điện thoại/camera ngoài quay sao cho cùng frame thấy đồng hồ thật và màn hình BTMH. Lấy ít nhất 10 mẫu ở đầu, 10 ở giữa, 10 ở cuối soak; hiệu hai giá trị trong cùng frame là độ trễ camera → màn hình. Ghi FPS của máy quay/sai số đọc và min/median/p95/max; nếu dùng hai đồng hồ riêng phải ghi cách đồng bộ và sai số. Mục tiêu LAN **<300 ms**; jitter/RTT/playout buffer hoặc `videoLatencyMs=null` không chứng minh đạt. Nếu không có phép đo đủ tin cậy, ghi **BLOCKED**.
4. Ghi rõ đoạn mất mạng/chuyển trang ngoài bài soak ổn định. Lặp bài 5 phút sau khi reconnect phục hồi để chứng minh không tích lũy trễ; kết quả fault/recovery của H07 không được xóa khỏi biên bản.
5. Đóng toàn bộ vùng xem rồi đăng xuất các tab. Dùng phiên kỹ thuật chỉ đọc status để chờ cleanup hoàn tất; pending/WebRTC phiên cũ phải về 0. Gateway on-demand có thể đóng nguồn trễ hơn click; AI/recorder còn hoạt động không bị tính nhầm thành browser leak.
6. Bằng chứng gồm timestamp, bảng stats đã lọc, video đo đồng hồ và PASS/FAIL/BLOCKED từng hàng. Không lưu config runtime, token, credentials, dữ liệu khách hàng hoặc raw network headers vào source.

## 5. Giao diện và môi trường còn phải nghiệm thu

| ID | Môi trường và các bước | Hiện tại |
| --- | --- | --- |
| U01 | Browser thật ở viewport **390/768/1440 px**: đăng nhập và kiểm tra dashboard, nhân sự/enrollment, recognition, khách, incidents, live grid, playback/history, HR/ca, reports, system/admin security. Kiểm tra chữ/nút không che nhau, table cuộn được, modal nằm trong viewport, media giữ đúng tỷ lệ và trạng thái rỗng/lỗi rõ. Chụp bằng chứng không chứa dữ liệu khách hàng. | BLOCKED — chưa có browser render để nghiệm thu |
| U02 | Dùng Tab/Shift+Tab, Enter/Space và nút đóng modal có tên: focus nhìn rõ, thứ tự hợp lý, không chạy vào shell inert khi login gate mở hoặc control bị khóa/ẩn theo quyền. Thử reduced-motion, logout và các vai trò RBAC hiện có. | BLOCKED — source audit không chứng minh focus/computed style |
| W01 | Windows runtime đã provision trong profile thử nghiệm riêng; ngắt Internet nhưng giữ LAN camera. Restart bằng launcher hiện có; kiểm tra auth, video/fallback, AI/PAD, recorder và dữ liệu thử nghiệm tồn tại qua restart. Không cài/tải thêm dependency trong bài offline. | BLOCKED — chưa chạy offline Windows thật |
| P01 | PostgreSQL test cluster/database **riêng biệt**, chỉ dữ liệu tổng hợp, role/config theo runtime hiện có. Kiểm tra registry persistence, RBAC, attendance, reconnect và restart trong profile đó; xác nhận không chạm database/DataRoot khách hàng. SQLite/mocks không thay thế kết quả này. | BLOCKED — chưa chạy PostgreSQL isolated thật |

Không ghi PASS cho U01/U02 từ HTML/CSS source, screenshot giả hoặc logical DOM tests. Không ghi PASS cho W01/P01 từ compile, release verifier hoặc SQLite.

## 6. Checkpoint và rollback khi bàn giao

Giữ nguyên checkpoint WebRTC source-only `backups/CODEX_WEBRTC_PRE_V550_20261006.zip`: **210 entries**, CRC đã kiểm tra; SHA-256 **`8894f11fcaba3caa9bda541d6b0f19b325dc282685c04f84d743b991f9b61fac`**. Bằng chứng kiểm tra được ghi trong [QA_V550.md](QA_V550.md) và [ExecPlan](EXECPLAN_BTMH_V550.md); không sửa/xóa archive này.

Không rollback tự động trong đợt QA. Nếu cần rollback theo quyết định riêng sau bàn giao, chỉ khôi phục source từ checkpoint sau khi dừng runtime và lưu riêng source hiện tại; database, credentials, DataRoot và `%LOCALAPPDATA%\CampusFace` phải giữ nguyên. Không `git reset --hard`, discard source hoặc xóa dữ liệu/checkpoint.

Chưa tạo **Easy Install final**. Core regression còn FAIL thì không được tạo; automated PASS cũng không thay thế những nghiệm thu **BLOCKED** phía trên. Chỉ chốt production/hardware acceptance sau khi có biên bản đo thật đủ điều kiện.
