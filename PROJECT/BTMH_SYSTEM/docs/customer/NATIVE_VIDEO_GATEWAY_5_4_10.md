# Hướng dẫn BTMH 5.4.10 - Native Video Gateway

## Cập nhật

1. Dừng bản cũ bằng `04_DUNG_HE_THONG.bat`.
2. Giải nén Easy Install 5.4.10 vào thư mục mới.
3. Không xóa `%LOCALAPPDATA%\CampusFace`.
4. Chạy `01_CAI_DAT_LAN_DAU.bat` bằng tài khoản Windows đang dùng, không `Run as administrator`.
5. Lần cài MediaMTX đầu tiên cần Internet để tải đúng bản đã pin và kiểm SHA-256. Sau khi runtime đã có, hệ thống tiếp tục chạy local/offline.
6. Chạy `02_KHOI_DONG_HE_THONG.bat`, mở `http://127.0.0.1:8100`, nhấn `Ctrl+F5`.

## Cách biết native gateway đang được dùng

Live View 5.4.10 ưu tiên `NATIVE_GATEWAY_WEBRTC`. Nếu gateway hoạt động, video được browser phát bằng `<video>` qua WHEP/WebRTC thay vì chuỗi JPEG/Canvas.

Có thể dùng trạng thái hệ thống hoặc API kỹ thuật `/api/v1/media/gateway/status` với tài khoản có quyền camera để kiểm tra `available`, `process_alive`, `port_ready` và transport. API này không trả RTSP URI hay mật khẩu camera.

## Nghiệm thu

- Mở Nhận diện & chấm công trong 3-5 phút và di chuyển liên tục trước camera.
- Chuyển Tổng quan -> Nhận diện -> Xem trực tiếp -> Nhân sự -> quay lại Nhận diện.
- Video không được tích lũy độ trễ sau thời gian dài.
- Nếu AI chậm, video vẫn phải tiếp tục chuyển động; AI và Live View là hai đường độc lập.
- Kiểm tra transport thực tế. Nếu rơi xuống WebSocket/MJPEG/polling thì chưa đạt mục tiêu native video.

## Nếu WebRTC native không lên

Hikvision phải phát codec browser có thể đọc qua WebRTC. H.264 có B-frames là một trường hợp không tương thích phổ biến. Khi gặp trường hợp này, giữ nguyên kiến trúc gateway và chỉnh profile H.264 của camera sang profile không tạo B-frame/tương thích browser; không dùng JPEG polling làm giải pháp lâu dài.

Không gửi mật khẩu camera qua chat hoặc ảnh chụp màn hình. Nếu mật khẩu đã từng được chia sẻ, đổi mật khẩu sau khi nghiệm thu hoàn tất.
