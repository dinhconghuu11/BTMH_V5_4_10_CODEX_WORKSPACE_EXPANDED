# BTMH 5.5 — Hệ thiết kế giao diện

Tiếp nối 2026-10-09: `#recognitionSlots[data-layout="single"]` hiển thị một camera lớn theo yêu cầu mới, dùng controller/media owner hiện có. Dropdown đổi subscription xem, không đổi AI nền hoặc ghi hình. Overlay giữ contain/letterboxing/fullscreen mapping; dữ liệu tracking quá hạn 1 giây bị xóa, không dùng animation để kéo dài danh tính. Grid giám sát nhiều camera giữ nguyên.

Ảnh tham chiếu tiếp theo của người dùng được áp dụng qua `btmh_recognition_console.css`, load cuối và chỉ scope `#page-recognition`: nền navy, accent xanh, camera trái/chi tiết và lịch sử phải, thanh chọn camera phía dưới. Photo/status/history giữ controller đã kiểm thử. Thumbnail chỉ copy frame của media layer đang hiển thị, không gọi frame API hoặc mở decoder mới; clear bitmap khi đổi camera/store, hide, logout hoặc mất quyền. 390/768/1440/1920 px đã render với Chrome headless profile riêng, feed nhận diện rỗng và không kết nối API/camera: bốn trường hợp PASS, có kiểm tra bàn phím/overflow/hidden/scroll. Evidence: `frontend/.qa_recognition_console/visual-results.json`. Đây là kiểm chứng layout tĩnh, không phải nghiệm thu ảnh và camera Production.

Lớp thiết kế mới là `frontend/css/btmh_design_v550.css`, nạp sau bundle và media stylesheet hiện có. Hai lớp UI tiếp nối là `btmh_account_ui_v550.css` rồi `btmh_auth_ui_v550.css`. Chỉ kích hoạt khi `body` có class `btmh-v550`. Các class và ID trong HTML/renderer đang dùng là hợp đồng component; lớp mới bổ sung tokens và presentation, giữ logic nghiệp vụ và media lifecycle.

## Màu và typography

| Token | Giá trị | Sử dụng |
| --- | --- | --- |
| `--btmh-v550-burgundy` | `#521a2b` | Primary action, tiêu đề và trạng thái chọn |
| `--btmh-v550-burgundy-dark` | `#37131f` | Sidebar, auth brand panel và modal video header |
| `--btmh-v550-gold` | `#b68a38` | Border/accent nhỏ, card đang chọn |
| `--btmh-v550-gold-ink` | `#785a23` | Nhãn accent trên nền sáng và focus outline |
| `--btmh-v550-ivory` | `#f5f1e9` | Nền workspace và vùng metric |
| `--btmh-v550-paper` | `#fffdf9` | Panel, form, bảng và modal |
| `--btmh-v550-ink` | `#29232a` | Nội dung chính |
| `--btmh-v550-muted` | `#6c6162` | Nhãn phụ, metadata và empty state |
| `--btmh-v550-line` | `#dfd7ca` | Đường chia và border |
| Success / warning / danger | `#236343` / `#83591e` / `#9f2635` | Trạng thái có nhãn chữ tương ứng |

Font dùng Segoe UI/system sans-serif có sẵn trên Windows; không tải font hay asset từ mạng. Body 14 px, label 12–13 px, tiêu đề panel 20 px và page heading 20–24 px. Chữ số KPI/metrics dùng tabular numerals. Gold sáng dùng cho accent, không dùng làm chữ nhỏ trên nền trắng.

Contrast tính từ cặp màu token theo relative luminance: white/burgundy **13.62:1**, ink/paper **15.11:1**, muted/paper **5.87:1**, gold-ink/paper **6.29:1**, sidebar text/burgundy-dark **13.80:1**. Đây là phép tính trên token; chưa thay thế kiểm tra computed style, focus hoặc tất cả trạng thái rendered.

Official emblem, wordmark và jewelry artwork giữ file gốc, tỷ lệ hiển thị hiện có và `filter:none`. Không dựng lại logo, không thêm ảnh từ bên ngoài. Sidebar burgundy và nền ivory tạo nhận diện thương hiệu bằng bề mặt, chữ và khoảng cách, với shadow nhẹ và không có animation trang trí mới.

## Component chung

| Component | Selector hiện có | Quy tắc |
| --- | --- | --- |
| Shell/navigation | `#btmhSidebar`, `.nav-item`, `.btmh-nav-cluster-toggle`, `.topbar.v13-topbar` | Sidebar desktop 264 px; active có gold indicator; giữ open/close và permission |
| Panel/card/KPI | `.panel`, `.v5-dashboard-kpis article`, `.hr-report-kpis article`, `.prod-history-kpi`, `.v6-system-kpis article` | Paper, border nhất quán, radius 14 px, nhịp số/nhãn rõ |
| Action | `.btn.primary`, `.btn.ghost`, `.btn.danger`, `.btn.small` | Primary burgundy/white; secondary paper; danger có nhãn, màu và tint riêng |
| Input/filter | `.field`, `.student-filter-panel`, `.prod-history-filters`, `.hr-report-toolbar`, `.v5-form-grid` | Input 44 px, label rõ, textarea co giãn dọc, checkbox/radio giữ điều khiển gốc |
| Tabs | `.student-profile-tabs`, `.history-split-switch`, `.hr-report-period`, `.v4-layout-buttons` | Active burgundy, inactive paper; không thay sự kiện chọn |
| Table | `.student-enterprise-table`, `.prod-history-table`, `.hr-report-table`, `.pr-table`, `.table-wrap` | Header ivory, row 14 px padding, dữ liệu dễ đọc; giữ scroll wrapper và min-width nghiệp vụ |
| Row/empty/status | `.v4-presence-row`, `.v5-audit-row`, `.v5-incident-card`, `.empty-card`, `.pr-state` | Metadata rõ; empty message giữ nguyên nội dung; status dùng text cùng tint |
| Dialog | `.student-modal-card`, `.v12-modal-card`, `.prod-history-detail-card`, `#cameraConnectionDialog[open]` | Paper, cuộn trong viewport; giữ cơ chế dialog/open/hidden hiện có |
| Camera/player | `.entry-camera-wrap`, `.v4-camera-card`, `.v4-playback-player`, `.v4-camera-modal` | Bề mặt tối, status dễ đọc; không đổi video/canvas position, display, object-fit hoặc layering |
| Diagnostics | `#btmhPerformanceDetails`, `.btmh-performance-metric` | Collapsed mặc định; nhãn + số rõ; `null` thành Chưa đo |

Matrix module và nhiệm vụ người sử dụng nằm trong `PRODUCT.md`. Shared components phủ Tổng quan, Nhân sự, Đăng ký, Nhận diện, Khách, Sự cố, Live Grid, Playback, Hiện diện, Lịch sử, HR, Ca làm, Camera Center, Hệ thống và Tài khoản. Các dynamic card thực tế như `.v5-incident-card` và `.btmh-visitor-card` được style trực tiếp; watchlist vẫn có border cảnh báo và incident đang chọn có accent rõ.

## Responsive và khả năng truy cập

| Viewport mục tiêu | Presentation theo source |
| --- | --- |
| 1440 px | Sidebar 264 px, workspace có khoảng cách 24–28 px; cards/tables giữ layout desktop hiện có |
| 768 px | Sidebar theo off-canvas menu hiện có; workspace toàn chiều rộng; form/playback/recognition/system columns chuyển dọc |
| 390 px | Margin 12 px, form một cột, KPI gọn, modal giới hạn trong viewport, metadata/video flags wrap, bảng cuộn trong wrapper |

Button chính và input tối thiểu 44 px; compact table actions giữ 36 px. `:focus-visible` dùng outline 3 px, gồm button, link, input, summary và phần tử có tabindex. Reduced-motion tắt animation/transition theo media query. Decorative auth animation đã tắt; scanner và trạng thái nghiệp vụ không bị đổi bằng CSS.

HTML giữ ID cũ, main landmark duy nhất, nhãn dialog/control và tên nút icon. Root auth flow quản lý `inert` của app shell khi auth gate mở. Rendered keyboard order, focus trap/return, menu tại màn hình hẹp và overflow vẫn cần kiểm tra bằng browser thật; không kết luận đạt từ selector đơn lẻ.

## Các hợp đồng bảo toàn

`[hidden]`, `.hidden`, `.permission-locked` và `.role-locked` phải thắng legacy display rules. Stylesheet có guard cụ thể cho nav trong `#btmhSidebar`, root/nested auth gate và `#runtimeMetrics[hidden]`. Không thêm display rule làm active page, panel bị khóa hoặc auth view ẩn xuất hiện. Inactive `.page` tiếp tục do application stylesheet kiểm soát.

Không style lại kích thước/position/object-fit của generic video, canvas hoặc img. `btmh_media_v5410.css` tiếp tục quyết định native video, canvas và overlay layers. Grid/modal giữ camera scope, nguồn main/small, negotiation owner, cancellation và các timer cleanup đã qua gate. Giao diện mới không phát sinh fetch, WebRTC peer, model call hay reader lease.

Không đổi threshold, PAD, chính sách audit hoặc dữ liệu. CSS không suy diễn trạng thái hardware. Unknown performance vẫn là unknown; FPS trình duyệt khác capture/AI FPS và độ trễ mạng chưa có phép đo vẫn Chưa đo.

## Evidence hiện tại

Source review đã đối chiếu class trong `frontend/index.html`, `frontend/js/app.js` và bundle hiện có; final stylesheet được load cuối và có activation class riêng. Visibility guard/media contract được review độc lập. Browser behavior gate Phase 4: **71 PASS**; gate này xác minh lifecycle JavaScript, không xác minh CSS rendered layout.

Tại checkpoint trước, rendered visual QA tại 390/768/1440 px, computed-style/focus và screenshot là **BLOCKED** vì công cụ UI không có browser được kết nối. Static preview không kích hoạt API, camera, AI, recorder hoặc customer data. Nghiệm thu hardware/MediaMTX/Hikvision/GPU/PostgreSQL và soak vẫn BLOCKED cho đến khi chạy thực tế; không ghi final visual/hardware PASS hoặc tạo installer từ trạng thái này.

## UI tiếp nối ngày 2026-10-07

Auth được chỉnh trên các view và ID hiện có: split brand/form trên desktop, card một cột trên tablet/mobile, cuộn để tới action ở màn hình thấp, label mật khẩu riêng với nút hiện/ẩn, feedback có live region. Artwork và font vẫn dùng local. Menu tài khoản hiển thị danh tính/vai trò, điều hướng theo quyền và đăng xuất qua API hiện có; có keyboard navigation, focus return và đóng theo lifecycle. CSS mới khắc phục header cắt dropdown và rule cũ ẩn user chip dưới 980 px. Các HUD kỹ thuật trên video được ẩn; kết quả nhận diện và lớp transport giữ nguyên chức năng.

Kiểm tra render riêng cho auth/account đã chạy trên preview tĩnh bằng Chrome headless với profile riêng: 11 tình huống tại 390/768/1440 px và màn hình cao 600 px. Có screenshot, kiểm tra CSS/visibility/overflow và khả năng cuộn tới action trong `frontend/.qa_preview_v550/visual-results.json`. Đây là evidence cho hai phần UI này; chưa nghiệm thu toàn bộ ứng dụng hoặc camera/auth server thật. Sau yêu cầu chỉ chạy trong sandbox, không mở thêm browser hoặc chạy regression ngoài sandbox. Xem `docs/UI_RESUME_QA_20261007.md` cho kết quả kiểm tra tập trung và rollback.

## MASTER finish checkpoint — 2026-10-08

Giữ visual world và auth đã hoàn thành; các surface mới dùng Operate mode: recognition 4 slots/recent, history ba tab, management dashboard, camera business configuration, profile/password và QR/mobile approval. Four slots không là camera registry limit/AI control. Sequence helper giải thích `#NNNN` theo camera/ngày, không phải visits. Recent feed phân biệt unknown identity và blocked verification; màu label trên video giữ hợp đồng recognition/PAD cũ.

Report filters tự áp dụng khi thay đổi; Enter tìm kiếm, Tải lại refresh, Xóa bộ lọc đưa về ngày hiện tại/all permitted. Secondary filters nằm trong native details với số filter đang dùng. Camera configuration giữ draft trong RAM cùng actor/phiên/camera qua tab/navigation suspension, luôn stop preview/abort requests; reload scoped registry/config trước restore và xóa khi logout/actor change/permission/camera revocation. Không browser storage hay connection credential draft.

Mobile enrollment chỉ gửi mẫu chờ duyệt; không success icon cố định cho rejected/expired/cancelled. Live regions guidance/PAD/ready chỉ đổi text khi nội dung server thay đổi; recent automatic polls không announce cùng nội dung mỗi lần. Admin review label nêu reason bắt buộc và giải thích prerequisites khi decision disabled. Font mobile cùng Segoe UI/local stack. Dashboard source copy đã khôi phục UTF-8; không đổi KPI logic.

Impeccable critique dùng hai isolated agents sau functional gate: A design review hoàn tất trước khi B detector findings tới parent. Score26/40 là assessment trước polish, không phải rendered score mới. Snapshot `.impeccable/critique/2026-10-08T13-45-13Z__frontend-index-html.md` và B evidence được lưu; scoped priorities đã sửa và snapshot đóng. Detector index9/enroll0 có unresolved external stylesheet warnings; runtime image/type/placeholder findings được source-classify, playback contrast candidate ngoài scope giữ lại. Không detector rerun, live server hay overlay injection.

Current browser inventory vẫn `apps=[]/browsers=[]`; current rendered layout/computed-style/keyboard/contrast **BLOCKED**. Source/VM confirmation sau polish: recent13, camera17, report25, mobile22, admin25 PASS; changed JS syntax PASS. Đây không thay thế nghiệm thu 390/768/1440, điện thoại HTTPS/PAD hoặc hardware. Xem final report cho SQL/security/state tests và acceptance boundaries.
