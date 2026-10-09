BAO TIN MANH HAI 5.4.4 - CAMERA SAFE HANDOVER

# Bảo Tín Mạnh Hải 5.4.4 - Camera Safe Handover

**Release Candidate. Bản nâng cấp từ 5.4.3, tập trung sửa lỗi chuyển camera.**

## Cập nhật trên máy Windows

1. Tạo backup bằng chức năng sao lưu của phần mềm. Không sao chép thư mục PostgreSQL đang chạy để thay cho backup.
2. Chạy `04_DUNG_HE_THONG.bat` của bản cũ. Đóng các tab BTMH cũ; không chạy hai bản cùng lúc.
3. Giải nén toàn bộ Easy Install vào thư mục mới, ví dụ `C:\BTMH_SECURITY_544`. Không đổi tên hoặc di chuyển riêng `_HE_THONG_BTMH_KHONG_XOA`.
4. Dùng đúng tài khoản Windows đã cài bản cũ. Nhấp đúp `01_CAI_DAT_LAN_DAU.bat` bình thường, **không Run as administrator**. Lần cài/cập nhật có thể cần Internet.
5. Chạy `02_KHOI_DONG_HE_THONG.bat`. Mở `http://127.0.0.1:8100` và nhấn **Ctrl + F5**.
6. Đăng nhập bằng tài khoản hiện có; không tạo lại Chủ sở hữu.

**Không xóa `%LOCALAPPDATA%\CampusFace` hoặc data root đang dùng.** Bản vá không có thao tác reset database, nhân viên, FaceID, tài khoản hay lịch sử. Chính sách SMS/MFA hiện có được giữ nguyên.

## Kết nối Hikvision

Trong **Nhận diện & chấm công**, chọn Hikvision rồi bấm **Sửa kết nối**. Đối chiếu thông tin với nguồn VLC đang xem được.

Với camera trong ảnh Hữu đã gửi, thông tin cần kiểm tra là:

| Trường | Giá trị đối chiếu |
|---|---|
| IP | `192.168.10.200` |
| Cổng | `554` |
| Đường dẫn | `/Streaming/Channels/101` |
| Tài khoản, mật khẩu | Nhập trực tiếp thông tin camera thật |

Đây là thông tin từ ảnh kiểm tra của Hữu, **không phải IP cố định cho mọi bản cài**. Phần mềm không tự ghi đè IP hay mật khẩu đã lưu. Để trống mật khẩu trong hộp sửa là giữ mật khẩu cũ; nhập mật khẩu mới khi cần thay. Không nhập chuỗi `***`, không gửi mật khẩu qua chat.

**Lưu kết nối -> Kiểm tra kết nối -> Chuyển nguồn.**

Lưu cấu hình không tự dừng camera đang chạy. Bước kiểm tra đọc 5 khung hình thật, không chỉ ping IP. Khi bấm Chuyển nguồn, phần mềm kiểm tra lại và giữ chính bộ đọc đã thành công, tránh đóng/mở lại camera mới.

Camera hiện tại vẫn chạy trong lúc thử nguồn mới. Nếu nguồn mới lỗi, nguồn cũ được giữ lại **khi nó vẫn còn kết nối/tạo hình**. Không thể giữ hình trực tiếp nếu cả hai thiết bị đều mất kết nối.

## Đọc kết quả kiểm tra

- `AUTH_FAILED`: camera trả lỗi xác thực/quyền truy cập. Kiểm tra tài khoản, mật khẩu và quyền xem hình.
- `PATH_NOT_FOUND`: kiểm tra đường dẫn luồng.
- `CONNECTION_REFUSED` / `UNREACHABLE`: kiểm tra IP, cổng, đường mạng.
- `TIMEOUT` / `OPEN_FAILED` / `READ_FAILED`: không nhận đủ hình; có thể liên quan luồng, bộ giải mã, mạng hoặc giới hạn kết nối. Không kết luận sai mật khẩu nếu camera chưa trả mã xác thực.
- `AI_BUSY`: chưa đổi nguồn vì nhận diện đang hoàn tất khung hình; thử lại.
- `COMMIT_FAILED`: nguồn mới đã có hình nhưng chưa hoàn tất đổi nguồn; giữ camera cũ và báo kỹ thuật.

Các chỉ số FPS/kích thước là kết quả quan sát từ khung hình. Thời gian kiểm tra không phải độ trễ truyền hình đầu-cuối đã đo.

## Nghiệm thu trên máy thật

Cho laptop camera chạy -> chuyển Hikvision -> về laptop -> lặp lại, đồng thời chuyển qua Nhân sự, Lịch sử, Cài đặt. Thử mất kết nối nguồn mới khi nguồn cũ còn chạy. Không thử mật khẩu sai lặp nhiều lần với camera thật để tránh khóa tài khoản.

Chưa nghiệm thu Windows/PostgreSQL/Hikvision thật, FaceID/PAD/GPU, PTZ vật lý và SMS thật trong môi trường này. Xem báo cáo QA trước khi bàn giao.

`03_KIEM_TRA_HE_THONG.bat` kiểm tra runtime máy cài. `VERIFY_RELEASE.py` dành cho kỹ thuật, cần pytest/Node.js; Node không phải yêu cầu để người dùng chạy web.
