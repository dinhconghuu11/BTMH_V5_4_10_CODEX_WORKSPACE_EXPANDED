# BTMH — Quản lý nhận diện, an ninh và chấm công

BTMH phục vụ vận hành cửa hàng Bảo Tín Mạnh Hải trên Windows, xử lý tại máy và sử dụng được ngoại tuyến sau khi cài đặt đầy đủ. Giao diện ưu tiên việc đang cần làm: xem tình trạng cửa hàng, xác minh người xuất hiện, quản lý nhân sự và truy lại bằng chứng. Dữ liệu camera đã cấu hình lấy từ camera registry trong database.

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
