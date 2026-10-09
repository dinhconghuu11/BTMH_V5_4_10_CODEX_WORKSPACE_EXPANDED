# Bảo Tín Mạnh Hải 5.4.10 - Native Video Gateway RC

Bản 5.4.10 tập trung xử lý triệt để tầng Live View: Hikvision RTSP H.264 được đưa qua MediaMTX local và phát tới browser bằng WHEP/WebRTC + `<video>`. Python WebRTC/JPEG/MJPEG/snapshot vẫn tồn tại dưới dạng fallback an toàn, nhưng không còn là đường ưu tiên.

## Nâng cấp từ 5.4.9

1. Dừng bản cũ bằng `04_DUNG_HE_THONG.bat`.
2. Giải nén Easy Install vào thư mục mới.
3. Chạy `01_CAI_DAT_LAN_DAU.bat` bình thường, **không Run as administrator**. Lần đầu cần Internet để cài MediaMTX runtime đã pin và kiểm SHA-256.
4. Chạy `02_KHOI_DONG_HE_THONG.bat`.
5. Mở `http://127.0.0.1:8100` và nhấn `Ctrl+F5`.

**Không xóa `%LOCALAPPDATA%\CampusFace`.** Dữ liệu PostgreSQL, tài khoản, nhân sự, FaceID, camera registry và lịch sử được giữ nguyên.

## Kiến trúc live video

```text
Hikvision /101 H.264
  -> MediaMTX localhost
  -> WHEP/WebRTC
  -> browser <video>
```

Camera secret chỉ được cấp cho child process MediaMTX bằng environment; YAML, browser và API trạng thái không chứa secret. Log gateway được lọc RTSP userinfo trước khi ghi file.

## Phạm vi không thay đổi

FaceID/PAD model, threshold, Best Shot, attendance, PostgreSQL, RBAC, SMS và Camera Registry 5.4.7 không được viết lại trong 5.4.10.

## Tài liệu

- `docs/customer/NATIVE_VIDEO_GATEWAY_5_4_10.md`
- `CHANGELOG_V5_4_10_NATIVE_VIDEO_GATEWAY.md`
- `VERIFY_RELEASE.py`

Đây là Release Candidate. Automated checks không thay thế nghiệm thu Windows + Hikvision thật. Nếu native WebRTC không lên và hệ thống rơi xuống fallback, kiểm tra codec/profile H.264; H.264 chứa B-frames có thể không được browser WebRTC hỗ trợ.
