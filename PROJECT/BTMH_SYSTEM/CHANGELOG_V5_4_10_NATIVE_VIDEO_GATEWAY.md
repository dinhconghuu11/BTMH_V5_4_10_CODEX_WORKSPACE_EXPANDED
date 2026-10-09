# BTMH 5.4.10 - Native Video Gateway

## Mục tiêu

5.4.10 thay đường Live View chính từ chuỗi ảnh JPEG do Python/OpenCV mã hóa sang video WebRTC/WHEP do MediaMTX chuyển tiếp từ RTSP H.264. Mục tiêu là tách hoàn toàn trải nghiệm xem camera khỏi nhịp xử lý FaceID/PAD và loại bỏ tải encode/decode JPEG không cần thiết trên đường hiển thị chính.

## Kiến trúc chính

```text
Hikvision RTSP H.264 (/101)
        -> MediaMTX local gateway
        -> WHEP / WebRTC
        -> browser <video>
```

Pipeline AI hiện hữu vẫn độc lập và không bị thay model/threshold trong bản này. Python WebRTC, WebSocket JPEG ACK-paced, MJPEG và HTTP snapshot được giữ lại theo thứ tự fallback có giới hạn, không còn là đường Live View ưu tiên.

## Thay đổi

- Thêm `module_app/media_gateway_v5410.py` để quản lý MediaMTX local, watchdog, restart và trạng thái gateway.
- Thêm `frontend/js/btmh_media_v5410.js`; native WHEP/WebRTC luôn được thử trước.
- Browser dùng `<video>` cho native gateway; không dùng Canvas/JPEG trên đường chính.
- Camera RTSP được đưa vào MediaMTX bằng biến môi trường của child process; YAML trên đĩa không chứa URI/tài khoản/mật khẩu camera.
- Log MediaMTX được BTMH thu và lọc RTSP userinfo trước khi ghi ra file.
- MediaMTX chỉ bind `127.0.0.1` trong cấu hình mặc định của bản một máy/một cửa hàng.
- Thêm watchdog để gateway được khởi động lại độc lập, không restart toàn bộ web.
- Thêm API trạng thái/restart gateway theo RBAC `camera.live` / `camera.configure`.
- Thêm installer MediaMTX 1.21.1, pin SHA-256 và từ chối archive sai hash.
- Không thay Camera Registry 5.4.7, FaceID, Passive PAD, Best Shot, attendance, PostgreSQL, RBAC hoặc SMS.

## Bảo mật

- Không ghi camera secret vào MediaMTX YAML.
- Không trả RTSP URI hoặc secret qua API trạng thái gateway.
- Không đưa secret vào browser/localStorage.
- Log gateway đi qua bộ lọc userinfo trước khi lưu.
- MediaMTX WebRTC/API/metrics mặc định chỉ lắng nghe localhost.

## Fallback

Thứ tự:

1. `MEDIAMTX_WHEP_WEBRTC`
2. `PYTHON_WEBRTC`
3. `WEBSOCKET_ACK_BITMAP`
4. `MJPEG`
5. `HTTP_SNAPSHOT`

Nếu native gateway không tương thích codec hoặc không khởi động được, BTMH vẫn có khả năng hiển thị bằng đường cũ. Fallback có thể kém mượt hơn và được coi là chế độ an toàn, không phải mục tiêu hiệu năng của 5.4.10.

## Giới hạn nghiệm thu

Môi trường build hiện tại không phải Windows và không có camera Hikvision vật lý, vì vậy MediaMTX + WHEP + camera thật phải được nghiệm thu trên máy khách. H.264 có B-frames có thể không được browser WebRTC hỗ trợ; trong trường hợp đó cần chỉnh profile/encoding của camera hoặc tạo profile tương thích, không quay lại JPEG làm kiến trúc chính.
