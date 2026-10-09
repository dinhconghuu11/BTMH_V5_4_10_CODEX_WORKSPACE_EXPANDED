# BTMH — Quản lý nhận diện, an ninh và chấm công

Yêu cầu tiếp nối 2026-10-09: trang Nhận diện & chấm công dùng **một camera lớn**, chọn từ registry được cấp quyền. Tính năng xem bốn camera đồng thời giữ ở Camera & giám sát. Thay đổi này thay thế yêu cầu bốn slot trên trang Nhận diện được ghi ngày 2026-10-08; giới hạn tối đa bốn camera AI-active và xử lý AI nền không đổi.

Bố cục theo ảnh tham chiếu người dùng bổ sung cùng ngày: vùng Nhận diện dùng nền tối, camera lớn bên trái, chi tiết và lịch sử ảnh bên phải, thanh chọn camera bên dưới. Thanh chọn không tạo thêm luồng; chỉ camera đang xem có thumbnail từ frame đang hiển thị. Ảnh người vẫn là saved evidence đúng sự kiện và quyền, không dùng ảnh mẫu để lấp trạng thái chờ. Sidebar và các trang khác giữ hệ thiết kế hiện có.

<!-- impeccable:product-schema 1 -->

BTMH phục vụ vận hành cửa hàng Bảo Tín Mạnh Hải trên Windows, xử lý tại máy và sử dụng được ngoại tuyến sau khi cài đặt đầy đủ. Giao diện ưu tiên việc đang cần làm: xem tình trạng cửa hàng, xác minh người xuất hiện, quản lý nhân sự và truy lại bằng chứng. Dữ liệu camera đã cấu hình lấy từ camera registry trong database.

## Platform

web

## Người sử dụng

- Người vận hành xem camera, trạng thái nhận diện, lượt khách và sự cố trong phạm vi quyền được cấp.
- Nhân sự quản lý hồ sơ, đăng ký FaceID, ca làm, lịch sử hiện diện và báo cáo theo quyền nghiệp vụ.
- Quản lý cửa hàng theo dõi hoạt động, xem bằng chứng và thực hiện các điều chỉnh có audit.
- Quản trị viên và kỹ thuật viên quản lý tài khoản, camera, sức khỏe hệ thống, backup và chẩn đoán theo quyền riêng của từng chức năng.

Vai trò và permission được máy chủ kiểm tra. Việc ẩn nút hoặc menu là cách trình bày quyền hiện có; CSS không cấp quyền truy cập.

## Phạm vi module

| Module hiện có | Công việc chính | Hướng trình bày 5.5 |
| --- | --- | --- |
| Tổng quan — `page-dashboard` | Tình trạng cửa hàng, camera, hiện diện và sự kiện gần nhất | KPI rõ, thao tác nhanh, bảng trạng thái gọn |
| Nhân sự — `page-students` | Tìm/lọc hồ sơ, xem chi tiết, FaceID và lịch sử cá nhân | Bộ lọc thống nhất, bảng dễ đọc, tab hồ sơ và modal cùng hệ thiết kế |
| Đăng ký — `page-register` | Hồ sơ và phiên thu FaceID nhiều góc | Tách bước hồ sơ/quét; giữ camera, hướng dẫn và trạng thái xác minh |
| Nhận diện — `page-recognition` | Quan sát camera vào cửa, FaceID/PAD và sự kiện | Camera là vùng quan sát chính; trạng thái và bằng chứng có thứ bậc rõ |
| Khách — `page-visitors` | Theo dõi lượt khách, best shots và đánh giá của người vận hành | Card sáng, metadata rõ, cảnh báo watchlist còn nổi bật |
| Sự cố — `page-incidents` | Hồ sơ sự cố, ảnh/video liên quan và Evidence Lock | Danh sách và nội dung chi tiết, trạng thái chọn rõ, hành động theo quyền |
| Camera trực tiếp — `page-live-grid`, `page-live-monitor` | Grid camera và xem lớn từng camera | Vùng video tối, chữ trạng thái dễ đọc, điều khiển bố cục nhất quán |
| Xem lại — `page-playback` | Recording, timeline và clip | Bộ lọc và panel thống nhất, giữ player và timeline hiện có |
| Hiện diện — `page-operations` | Danh sách đang hiện diện | KPI và hàng dữ liệu cùng nhịp với Tổng quan |
| Lịch sử — `page-history` | Nhận diện, sự kiện nhân sự, phiên và tổng hợp | Tab, bộ lọc, bảng cuộn ngang và chi tiết sự kiện thống nhất |
| Báo cáo nhân sự — `page-hr-report` | Báo cáo ngày/tuần/tháng, xuất file và quy tắc ca | KPI, period tabs, bảng và form dùng cùng tokens |
| Ca làm — `page-work-shifts` | Ca, gán ca và hiệu chỉnh chấm công | Form rõ, ghi nhận audit, giữ dữ liệu camera gốc |
| Điều khiển/quản lý camera — `page-camera-control`, `page-ops-center` | Thiết bị, chuyển nguồn và kiểm tra ngoại lệ | Điều khiển và báo cáo trạng thái theo cùng hệ component |
| Hệ thống — `page-system` | Health, camera, backup, Edge PC và chẩn đoán | Health thường dùng ở phía trước; chi tiết kỹ thuật mặc định đóng |
| Tài khoản — `page-admin-security` | RBAC, phiên, xác thực và quản lý người dùng | Form, card quyền và trạng thái bảo mật rõ; hành động chỉ hiện khi được phép |

## Hành vi phải giữ

Video trực tiếp và AI hoạt động độc lập. Native gateway/WebRTC là đường ưu tiên; các transport JPEG là fallback có trạng thái rõ. Grid nhỏ có thể yêu cầu luồng phụ đã được xác nhận; single view, fullscreen, recording và bằng chứng giữ luồng chính. Khi luồng nhỏ chưa sẵn sàng, lý do fallback được thể hiện rõ và luồng chính tiếp tục nếu có thể.

Camera handover, source epoch, ownership và retirement proof tiếp tục kiểm soát việc chuyển nguồn. Status-only reads không tạo auxiliary decoder. Polling và streaming có reader leases; đóng view, đổi trang, logout hoặc tab ẩn phải giải phóng phần presentation tương ứng. Lớp thiết kế không thay ID, API, listener, timer, source hoặc kích thước/layer của video và overlay.

FaceID threshold, Passive PAD, anti-spoof, xác minh nhiều khung hình, attendance và chính sách bằng chứng được giữ nguyên. Camera credentials, database, `%LOCALAPPDATA%\CampusFace` và checkpoint rollback không thuộc phạm vi thiết kế. RTSP credentials không xuất hiện trong browser storage, frontend, log hay tài liệu.

## Trạng thái và số liệu

Trạng thái sử dụng chữ cùng màu, để người dùng phân biệt kết nối, đang chờ, lỗi và cảnh báo. Không coi một kết nối WebRTC đã mở là hình ảnh đã được giải mã/hiển thị. Lượt khách chưa xác định không được trình bày như nhân viên đã xác minh.

Chi tiết hiệu năng cần `system.diagnostics`, chỉ đọc khi đã đăng nhập, đang ở trang Hệ thống, details mở và document đang hiển thị. Backend trả số/enum allowlisted từ cached state. `null` được hiển thị là **Chưa đo**; số 0 vẫn là phép đo 0. FPS trình duyệt được tách khỏi FPS capture/AI. Độ trễ mạng chưa được đo không suy ra từ jitter buffer hay thời gian xử lý AI.

## Kiểm chứng và giới hạn hiện tại

Phase 1–4 đã qua các automated gate được ghi trong `docs/EXECPLAN_BTMH_V550.md`. Phase 5 dùng source-contract review và các browser lifecycle regressions; kiểm tra rendered layout, keyboard focus và screenshot tại 390/768/1440 px hiện **BLOCKED** vì không có browser được kết nối với công cụ UI. Không ghi nhận visual PASS chỉ từ việc đọc CSS/HTML.

MediaMTX/Hikvision thật, model/GPU thật, độ trễ LAN, rendered FPS thực tế, soak và PostgreSQL thật vẫn **BLOCKED** khi chưa nghiệm thu trong môi trường tương ứng. Không tạo Easy Install final khi core regression còn FAIL. Source rollback archive `backups/CODEX_WEBRTC_PRE_V550_20261006.zip` phải được giữ nguyên; không rollback hoặc xóa dữ liệu để thực hiện redesign.

## Product Purpose

BTMH là hệ thống quản lý nhận diện, chấm công, camera và an ninh dành cho cửa hàng, với định hướng quản lý chuỗi cửa hàng. Sản phẩm đang được hoàn thiện để demo thực tế cho khách hàng; ưu tiên hoạt động ổn định tại cửa hàng và hoàn thành các công việc vận hành thực tế.

Giao diện quản lý phục vụ chủ yếu **Owner/Admin/Manager**. Các nhóm người sử dụng và quyền nghiệp vụ đã mô tả ở trên tiếp tục được giữ nguyên.

## Positioning

BTMH kết hợp camera, nhận diện, chấm công và an ninh trong một không gian quản trị nội bộ, vận hành local-first trên Windows. Định hướng nhiều cửa hàng/chi nhánh cần cho phép truy lại sự kiện theo đúng địa điểm và camera. Đây là định vị sản phẩm do người dùng xác nhận; tài liệu không đặt ra tuyên bố vượt trội so với đối thủ hoặc số liệu hiệu quả chưa có bằng chứng.

## Operating Context

- Môi trường triển khai chính là PC Windows tại cửa hàng; giao diện được sử dụng qua trình duyệt. Mobile web vẫn thuộc nền tảng `web`.
- Local-first và sự ổn định tại cửa hàng là ưu tiên vận hành. Khả năng ngoại tuyến giữ các điều kiện đã nêu trong nội dung hiện có; không suy ra rằng các tích hợp cần Internet luôn hoạt động khi mất mạng.
- Bối cảnh hiện tại là chuẩn bị demo thực tế cho khách hàng. Bằng chứng kiểm thử và các phần chưa nghiệm thu được ghi riêng bên dưới; mục tiêu demo không thay thế nghiệm thu.
- Cửa hàng/chi nhánh, khu vực và camera là ngữ cảnh nghiệp vụ cần đi cùng hoạt động quan sát, nhận diện và truy lịch sử.

## Yêu cầu sản phẩm được xác nhận — 2026-10-08

Các mục sau là yêu cầu và ràng buộc sản phẩm được người dùng xác nhận cho việc hoàn thiện demo và phát triển tiếp. Việc ghi vào PRODUCT.md không chứng nhận rằng source hiện tại đã triển khai hoặc kiểm thử đầy đủ từng mục.

### Tài khoản và cửa hàng

- **Owner/Admin tạo tài khoản**; không cho phép **public registration**. Quyền truy cập tiếp tục do máy chủ kiểm tra theo security policy hiện có.
- Hệ thống phải hỗ trợ **nhiều cửa hàng/chi nhánh**, phù hợp định hướng quản lý chuỗi.

### Danh tính và tổ chức camera

- Mỗi camera thuộc **một cửa hàng** và **một khu vực cụ thể**.
- Camera có **display name do quản trị viên đặt**, ví dụ **"Hà Đông - Cửa vào"**.
- **Camera ID nội bộ độc lập với tên hiển thị**. Đổi display name không được thay đổi định danh nội bộ hoặc làm mất liên kết lịch sử của camera.
- Các yêu cầu về cửa hàng/khu vực/tên hiển thị tiếp tục dùng camera registry trong database làm nguồn cấu hình chính thức; không hard-code dữ liệu khách hàng vào giao diện.

### Camera AI-active và bốn slot hiển thị

- **Bản demo hiện tại giới hạn tối đa 4 camera AI chạy đồng thời**. Đây là giới hạn camera AI đồng thời của demo, không phải giới hạn tổng số camera có thể được quản lý trong hệ thống.
- Trang **Nhận diện & chấm công có 4 camera slot linh hoạt**. Bốn slot biểu thị vùng hiển thị trên trang, không xác định tổng số camera của hệ thống.
- **Camera AI-active phải tiếp tục nhận diện ở backend kể cả khi camera đó không được hiển thị trên trình duyệt**. Việc đổi slot, đổi trang, ẩn tab hoặc đăng xuất chỉ giải phóng presentation tương ứng; không tự tắt AI-active ở backend.
- Phải chống nhận diện lặp liên tục bằng **tracking, identity cache, cooldown/deduplication** và giữ **queue AI có giới hạn**, không để queue tăng vô hạn. Giữ nguyên các quy tắc FaceID/PAD đã được bảo vệ.
- **Không được tính một detection frame là một khách hàng**. Dữ liệu phát hiện khung hình và số khách/lượt khách phải được phân biệt; thống kê khách cần tuân theo quy tắc theo dõi và chống đếm lặp của nghiệp vụ.

### Sự kiện và lịch sử nhận diện

- Mỗi **recognition event phải xác định được thời gian, cửa hàng, khu vực và camera**.
- Lịch sử nhận diện phải lọc được theo **ngày/tháng/năm, cửa hàng, khu vực và camera**.

## Brand Commitments

- Tên và tài sản thương hiệu Bảo Tín Mạnh Hải hiện có được giữ nguyên; sử dụng logo/emblem/artwork local đã có.
- Phong cách giao diện được người dùng xác nhận: **premium jewelry enterprise software**, sang trọng nhưng tối giản, phù hợp thao tác quản trị và vận hành.
- Brand: **burgundy/wine + ivory/warm white + gold accent nhẹ**. Đây là ràng buộc thương hiệu; chi tiết hệ thiết kế tiếp tục nằm trong DESIGN.md.
- Không hiển thị **RTSP, MediaMTX, decoder, transport hoặc developer diagnostics** trên **customer-facing UI**. Trạng thái sản phẩm phải dùng ngôn ngữ dễ hiểu và phản ánh đúng bằng chứng; lý do fallback không trình bày bằng tên transport hoặc chi tiết hạ tầng. Yêu cầu này bao gồm giao diện dùng trong demo khách hàng.
- Chi tiết chẩn đoán kỹ thuật được mô tả ở các phần hiện có chỉ dành cho phạm vi vận hành kỹ thuật có quyền riêng; không trở thành nội dung customer-facing. Các quyền và kiểm tra bảo mật hiện có phải tiếp tục được bảo toàn.
- Không thay đổi nghiệp vụ **FaceID/PAD**, **security policy** hoặc **camera architecture** chỉ để làm đẹp giao diện.

## Evidence on Hand

- Tài sản thương hiệu local: `frontend/img/btmh_official_logo.png`, `frontend/img/btmh_emblem.png`, `frontend/img/gold-jewelry-v543.svg`.
- Module, route và UI hiện có: `frontend/index.html`, `frontend/js/app.js`; hệ thiết kế hiện có được ghi trong `DESIGN.md`.
- Báo cáo checkpoint source/automated QA: `docs/EXECPLAN_BTMH_V550.md`, `docs/FINAL_QA_V550.md`. Không suy ra hardware hoặc production acceptance từ các báo cáo automated.
- Checkpoint UI ngày 2026-10-07 trong `docs/UI_RESUME_QA_20261007.md` ghi nhận **10 test account/auth**, **45 test media lifecycle** và **11 tình huống render tĩnh auth/account** đã PASS. Có ảnh desktop/mobile và kết quả tại `frontend/.qa_preview_v550/visual-results.json` cùng các PNG trong thư mục đó.
- Ghi chú visual **BLOCKED** trong phần kiểm chứng trước đó phản ánh checkpoint trước khi có evidence render auth/account này. Evidence mới chỉ áp dụng cho phần UI đã kiểm tra; toàn bộ ứng dụng, auth/SMS server thật và các môi trường camera/model/GPU/PostgreSQL thật chưa được chứng nhận từ preview.
- Preview tại `tests_browser/preview_ui_v550.py` loại bỏ product scripts và chặn API; ảnh preview không phải bằng chứng nhận diện hoặc dữ liệu khách hàng thật.
- Chưa có evidence trong checkpoint UI để xác nhận triển khai đầy đủ yêu cầu nhiều chi nhánh, 4 camera AI đồng thời, 4 slot linh hoạt hoặc toàn bộ bộ lọc lịch sử mới. Các yêu cầu này cần được đối chiếu source và kiểm thử trong task triển khai tương ứng.

## Product Principles

1. **Ổn định tại cửa hàng:** ưu tiên local-first trên Windows và khả năng hoàn thành công việc vận hành thực tế, kể cả khi dịch vụ ngoài hệ thống không sẵn sàng.
2. **Quyền và bí mật được bảo vệ:** quyền do máy chủ quyết định, tài khoản do Owner/Admin tạo; không public registration hoặc lộ camera credentials/chi tiết hạ tầng trên giao diện khách hàng.
3. **Quan sát độc lập với xử lý:** trạng thái hiển thị trên trình duyệt không quyết định việc nhận diện của camera AI-active; video và AI tiếp tục độc lập.
4. **Sự kiện có nguồn gốc, thống kê có nghĩa:** gắn thời gian/cửa hàng/khu vực/camera với recognition event; phân biệt detection frame với khách và dùng tracking/cache/cooldown/deduplication cùng queue có giới hạn.
5. **Bảo toàn nghiệp vụ và dữ liệu:** đổi giao diện không làm thay đổi FaceID/PAD, security policy, camera architecture, camera identity hoặc tính toàn vẹn của lịch sử và bằng chứng.

## Quyết định sản phẩm còn mở

Các chi tiết chưa được xác nhận ở đây gồm ma trận quyền theo từng chi nhánh, quy tắc đổi camera giữa bốn slot và định nghĩa khách/lượt ghé trong các tình huống tái xuất hiện. Các task triển khai tương ứng cần làm rõ trước khi áp dụng; không tự đặt threshold, thời gian cooldown, cấu trúc database hoặc cơ chế điều phối camera từ tài liệu init này.

## Quyết định và evidence tiếp nối — 2026-10-08

Các quyết định dưới đây bổ sung các mục còn mở ở checkpoint init; không xóa thông tin sản phẩm hoặc chứng nhận nghiệm thu thực tế:

- Mỗi slot chọn camera đã được cấp quyền từ registry. Thay đổi slot không thay đổi AI-active. Demo tiếp nhận tối đa bốn pipeline AI nền, dùng frame mới nhất và hàng đợi/cache hữu hạn.
- `#NNNN` là số thứ tự appearance của một camera trong ngày nghiệp vụ. Cùng appearance và Unknown → Verified giữ nguyên số; mỗi camera có counter riêng, ngày mới lúc 00:00 theo timezone cửa hàng tạo chuỗi mới. ID sự kiện không reset. Số này không dùng làm khách/lượt khách.
- Chấm công dựa trên ca được gán có ngày hiệu lực, timezone và ca qua đêm; giờ đầu vào hợp lệ được giữ riêng với last seen. Chỉ sự kiện OUT thực mới chốt giờ ra; mất dấu không tạo OUT hoặc suy ra giờ làm. Chưa gán ca được trình bày trung tính; chỉ kết luận vắng sau khi ca kết thúc theo policy hiện có.
- Một lượt khách cần IN hợp lệ qua đường/vùng cửa vào đã cấu hình. OUT thực đóng phiên; IN tiếp theo sau OUT là lượt mới. Không tuyên bố khách duy nhất xuyên camera. Phiên quan sát cũ và detection frame không cộng vào số lượt khách. Nhận diện từ face bbox cần khuôn mặt nhìn thấy khi qua đường; camera/cửa vào chồng lấn cần chọn một camera đếm chính.
- QR enrollment được phê duyệt trong phạm vi tối đa hai bảng mới, additive only: lời mời/token và yêu cầu duyệt. Desktop/điện thoại cùng pipeline chất lượng/PAD; PENDING chưa đưa mẫu vào FaceID. Owner/Admin APPROVE mới công bố mẫu; REJECT hoặc REQUEST REENROLLMENT giữ FaceID cũ. Token dùng một lần, hết hạn, thu hồi được và gắn nhân viên/cửa hàng đăng ký; không public registration.
- Cửa hàng đăng ký được Owner/Admin chọn rõ ràng và không tự tạo phân công nhân viên. Có phân công hiện hữu thì phải khớp ở lúc tạo và duyệt. Không có phân công thì giữ binding của yêu cầu, không tự chọn cửa hàng đầu tiên.
- Điện thoại capture cần HTTPS local được thiết bị tin cậy. QR được tạo bằng code local; không dùng CDN hoặc dịch vụ QR ngoài hệ thống. Mobile Viewer giữ quyền chỉ xem, tách với capability enrollment.

Các checkpoint source/SQL/state/lifecycle hiện tại nằm trong `docs/EXECPLAN_DEMO_PRODUCTION_LITE.md`, migration QR trong `docs/QR_MIGRATION_AUDIT_20261008.md`. Kiểm thử SQLite/Node và ASGI adapters không thay thế nghiệm thu PostgreSQL, key crypto cài đặt, camera/PAD/GPU/Windows hoặc điện thoại HTTPS. Rendered QA hiện tại vẫn cần browser được kết nối; ảnh auth/account cũ chỉ chứng minh checkpoint cũ.
