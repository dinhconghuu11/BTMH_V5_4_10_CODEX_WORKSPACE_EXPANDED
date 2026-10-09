# Báo cáo QA 5.4.3 - Realtime & UI Hardening

## Nguồn

Nâng cấp từ source/Easy Install 5.4.2 đã gửi. SHA-256 có trong `qa_5_4_3/input_fingerprints.json`; không ghi đè ZIP gốc.

## Lỗi đứng trang đã tái hiện

Trong `btmh_customer_v541.js` cũ, MutationObserver theo dõi class cụm menu Camera nhưng callback lại `classList.add('open')` lên chính cụm đó. Khi chọn module con, vòng callback tự kích hoạt liên tục và chặn luồng giao diện.

Bài tái hiện dùng nguyên script lấy từ ZIP cũ, không camera/AI: **1.001 callback**, chạm ngưỡng dừng bảo vệ. Bản mới cập nhật menu theo sự kiện, không observer này: **0 callback**, submenu mở đúng.

Đây là một nguyên nhân trực tiếp đã chứng minh, không phải kết luận mọi lỗi trên máy khách đều do nó. Không quy kết PAD là nguyên nhân chính chỉ từ warning cũ.

## Thay đổi

- Bỏ vòng observer; menu/submenu/aria-current theo sự kiện. Sidebar 320 px, icon duotone SVG, đủ tên, drawer trên mobile.
- Preview JPEG hữu hạn, tối đa 3 request đồng thời; hủy request và blob URL khi rời trang; không preview module ẩn.
- Single-flight cho health/recognition; timeout, đóng/nối lại WebSocket; hiện cảnh báo khi JPEG cũ, không giả vờ live.
- Sequence/tuổi JPEG từ encoder; MJPEG phụ kết thúc khi disconnect. Kiểm tra auth DB đồng bộ chạy ngoài async event loop.
- Giữ luồng capture/AI/encoder riêng sẵn có. **Không tắt chống giả mạo, không giảm ngưỡng nhận diện, không chấp nhận người khi PAD chậm.** Không tuyên bố đã viết PAD process riêng hay đạt 30 FPS.
- `/api/v1/camera/sources` liệt kê Registry, không mở camera để lấy danh sách. Có kiểm tra quyền, giữ USB/PTZ/IP/offline/disabled, trả alias thay RTSP credential.
- So sánh nguồn nội bộ không dùng URL đã che mật khẩu để tránh mở decoder trùng. USB index 1 không bị ép thành camera IP.
- Login: trái thương hiệu, phải form ivory; logo gốc, nhẫn vàng SVG minh họa (không phải ảnh sản phẩm thật). Giữ ghi nhớ tên và hỗ trợ, reduced-motion, asset offline.
- Không đổi schema nhân sự, xóa dữ liệu, reset tài khoản hay thay chính sách SMS/MFA.

