# Bảo Tín Mạnh Hải 5.4.5 - Bản vá kết nối RTSP

**Release Candidate, nâng cấp từ 5.4.4. Không viết lại FaceID, PAD hoặc cơ sở dữ liệu.**

## 1. Cập nhật an toàn

1. Tạo backup bằng chức năng sao lưu của phần mềm. Không sao chép thư mục PostgreSQL đang chạy để thay cho backup.
2. Chạy `04_DUNG_HE_THONG.bat` của bản cũ. Đóng các tab BTMH, không chạy hai bản đồng thời.
3. Giải nén ZIP Easy Install vào thư mục mới, ví dụ `C:\BTMH_SECURITY_545`. Giữ nguyên `_HE_THONG_BTMH_KHONG_XOA`.
4. Dùng đúng tài khoản Windows đã cài bản cũ, nhấp đúp `01_CAI_DAT_LAN_DAU.bat`. **Không Run as administrator.** Lần cài/cập nhật có thể cần Internet.
5. Chạy `02_KHOI_DONG_HE_THONG.bat`, mở `http://127.0.0.1:8100`, nhấn **Ctrl + F5**. Đăng nhập bằng tài khoản hiện có.

**Không xóa `%LOCALAPPDATA%\CampusFace` hoặc data root đang dùng.** Bản vá không reset tài khoản, FaceID, nhân viên, camera hay lịch sử; không thêm migration schema.

## 2. Đặt đúng nguồn camera

Vào **Nhận diện & chấm công -> chọn Hikvision -> Sửa kết nối**.

Mở **Dán địa chỉ RTSP đã kiểm tra**, dán địa chỉ đã hoạt động với camera của Hữu:

```text
rtsp://192.168.10.200:554/Streaming/Channels/101
```

Bấm **Áp dụng vào biểu mẫu**. Kiểm tra IP `192.168.10.200`, cổng `554`, đường dẫn `/Streaming/Channels/101`. Đây là thông tin từ ảnh Hữu cung cấp, không phải địa chỉ mặc định cho mọi cửa hàng.

Nhập tài khoản/mật khẩu camera trực tiếp trên PC. Để trống mật khẩu là giữ giá trị đã lưu; chỉ làm vậy khi mật khẩu cũ đúng. Không nhập chuỗi `***` và không gửi mật khẩu qua chat.

**Lưu kết nối -> Kiểm tra kết nối -> Chuyển nguồn.**

Dán địa chỉ chỉ điền biểu mẫu, không tự lưu và không đổi IP trên camera. Bản cập nhật cũng không tự ghi đè cấu hình đã lưu. Nếu bên dưới kết quả vẫn hiện `192.168.1.200`, hãy sửa lại đúng camera đang chọn.

Không cần reset camera, cập nhật firmware, cài plugin Hikvision hoặc chạy VLC để BTMH nhận hình. Giữ luồng `/101` H.264 1920x1080/25 FPS đã thử được; bản vá không tự đổi sang `/102` hay giảm chất lượng AI.

## 3. Đọc kết quả và lấy chẩn đoán

Bộ đọc RTSP mới hiện `FFMPEG-NATIVE` và `TCP` khi được sử dụng. Bước kiểm tra cần nhận ít nhất 5 khung hình liên tiếp và còn mới. FPS là tốc độ quan sát, không phải cam kết FPS của camera; `elapsed_ms` là thời gian kiểm tra, không phải độ trễ video đầu-cuối.

- `AUTH_FAILED`: camera từ chối xác thực/quyền xem. Không thử sai mật khẩu liên tục để tránh khóa tài khoản.
- `PATH_NOT_FOUND`: kiểm tra đường dẫn luồng.
- `CONNECTION_REFUSED`, `UNREACHABLE`, `TIMEOUT`: đối chiếu IP/cổng/mạng và phản hồi camera.
- `CAMERA_BUSY`: camera trả mã từ chối thêm phiên xem. Đóng phiên xem thử rồi kiểm tra lại.
- `DECODER_UNAVAILABLE`, `DECODER_OPTIONS`: kiểm tra runtime BTMH, không đổi cấu hình camera ngay.
- `OPEN_FAILED`, `READ_FAILED`: chưa đủ bằng chứng để kết luận sai mật khẩu hay codec.

Nếu thất bại, bấm **Sao chép chẩn đoán**. Bản sao chỉ chứa mã lỗi, nguồn đã loại thông tin đăng nhập, bộ đọc và thống kê khung hình; không gửi ảnh nhân viên, mật khẩu, token hay toàn bộ runtime.

Công cụ bổ sung: `CONG_CU_TUY_CHON\09_KIEM_TRA_RTSP.bat`. Nó chạy bằng private Python của BTMH, nhập mật khẩu kín trên máy, không đổi registry/FaceID/camera đang chạy. Kết quả lưu tại `logs\camera-diagnostic-latest.json` trong data root. Công cụ mở một phiên RTSP thử, nên không chạy nhiều bản đồng thời.

## 4. Phạm vi bản vá

Thêm bộ đọc FFmpeg độc lập cho RTSP, dùng executable từ dependency `imageio-ffmpeg==0.6.0` vốn đã có. Không thêm PyAV, không yêu cầu VLC và không tải file khi bấm chuyển camera.

Safe Handover cũ được giữ nguyên: kiểm tra nguồn mới trước, chỉ chuyển khi có hình; nguồn cũ còn hoạt động thì được giữ khi nguồn mới lỗi. Không thể cam kết hình trực tiếp nếu cả hai nguồn cùng mất kết nối.

Đường USB/laptop, FaceID, PAD, chấm công, PostgreSQL, phân quyền, SMS và giao diện đăng nhập không bị viết lại. Đối chiếu SHA-256 các module trọng yếu có trong báo cáo phạm vi.

## 5. Nghiệm thu và hoàn nguyên

Trên máy Hữu: Laptop -> Hikvision -> Laptop, lặp lại và chuyển các module. Kiểm tra hình và nhận diện thực tế, mạng mất/tái kết nối. Chưa có kết quả Windows/Hikvision vật lý thì chưa gọi là Customer Final.

Khi cần quay lại: dừng 5.4.5, chạy bản 5.4.4 từ thư mục cũ với cùng tài khoản Windows. Bản vá không đổi schema, nhưng cấu hình camera Hữu đã Lưu là dữ liệu dùng chung, không tự hoàn nguyên theo source.

Chế độ kỹ thuật: `BTMH_RTSP_READER=auto` (mặc định), `ffmpeg` (bắt buộc native), `opencv` (so sánh bộ đọc cũ). Không yêu cầu khách hàng tự đổi những biến này. `VERIFY_RELEASE.py` dành cho kỹ thuật, cần pytest và Node; không bắt buộc Node để sử dụng web.
