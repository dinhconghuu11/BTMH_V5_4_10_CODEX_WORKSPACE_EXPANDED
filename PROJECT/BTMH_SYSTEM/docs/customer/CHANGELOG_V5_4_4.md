# Báo cáo QA - BTMH 5.4.4 Camera Safe Handover

## Phạm vi và kết quả

Nâng cấp từ đúng ZIP Development/Easy Install 5.4.3. Không thay chính sách đăng nhập/SMS/MFA, không reset dữ liệu, không hạ ngưỡng FaceID/PAD.

| Bộ kiểm tra | Kết quả |
|---|---|
| Python/API regression (tests_v54) | 122 PASS, gồm 87 test cũ + 35 test camera mới |
| RTSP/RTP/H.264 trên loopback với OpenCV child process thật | 5 PASS |
| Giao diện kiểm tra/sửa camera | 25/25 PASS |
| Demo đăng nhập/thiết lập riêng | 23/23 PASS |
| VERIFY_RELEASE | 50 PASS, 0 FAIL |

## Những gì thực sự đã chạy

RTSP test tạo video mẫu H.264 bằng FFmpeg, phục vụ qua RTSP/RTP interleaved TCP trên `127.0.0.1`, rồi đọc bằng OpenCV trong tiến trình con mới. Không phải chỉ gán `isOpened=True`.

Năm bài RTSP: nhận 5 frame và frame tiếp tục tăng; mật khẩu có ký tự đặc biệt; phân loại lỗi 401; phân loại 404; ngắt tiến trình khi server không trả lời; chuyển qua lại hai nguồn RTSP 4 lần và giữ nguồn cũ tiếp tục phát hình khi nguồn mới trả 401. Các tình huống được gộp thành 5 test.

AI/preview worker trong bài chuyển RTSP được thay bằng stub để cô lập vấn đề capture; publisher và decoder thật vẫn chạy. Không dùng bài này để chứng minh chất lượng nhận diện sinh trắc.

UI test dùng Chromium `set_content`, mã toolbar/CSS/JS thật, nhưng fetch và storage giả lập. Kiểm tra chống bấm lặp, menu không bị vô hiệu hóa khi chờ, hiện lỗi, form sửa, không đổ mật khẩu cũ về trình duyệt, xóa mật khẩu nhập khi đóng form. Môi trường trình duyệt quản lý chặn điều hướng mạng, nên đây không phải browser end-to-end đến camera thật.

## Sửa đổi kỹ thuật

- Mỗi bộ đọc camera có tiến trình riêng. URL/credential qua stdin, không đưa vào command line; stderr chỉ chuyển thành mã lỗi cho phép.
- RTSP đọc qua TCP, software decoder; timeout open/read và deadline ngoài tiến trình. Parent giữ một latest frame, không xếp hàng frame vô hạn.
- Prepare -> 5 valid frames -> commit -> retire old process. Thất bại preflight/commit không đóng nguồn cũ đang làm việc. Chặn trùng candidate, có hủy khi shutdown.
- FaceID tiếp tục trên nguồn cũ lúc preflight. Commit đợi AI hoàn thành có giới hạn; source epoch ngăn preview cũ gắn nhãn nguồn mới.
- Camera Registry read không ghi đè IP/credential. Template đóng gói đánh dấu example_only, không tự trở thành camera thật.
- Fleet live-grid dùng cùng capture process và reservation để không tranh nguồn lúc chuyển; không tự lặp xác thực sau lỗi 401/404.
- Đường dẫn `/camera/test-source` cần quyền `camera.switch`; editor connection cần `camera.configure`. Không bỏ qua RBAC.

## Giới hạn và việc còn cần nghiệm thu

Linux/Python 3.13/OpenCV 4.13 trong môi trường kiểm thử khác bộ runtime Windows Python 3.12/OpenCV 4.11 của khách. Tests API dùng SQLite cô lập; chưa nghiệm thu PostgreSQL/DPAPI trên Windows.

Chưa có thiết bị Hikvision/WyreStorm/USB thật, H.265, PTZ vật lý, GPU hay model FaceID/PAD thật trong vòng test này. H.264 loopback dùng xác thực Basic; không thay thế kiểm tra firmware/cấu hình xác thực của camera thật.

Có chi phí RAM/CPU thêm cho decoder process; khi chuyển nguồn có thể tồn tại camera hiện tại và candidate song song. Chưa benchmark 100 camera hay SLA 24/7. Sau một lần chuyển thành công, nếu camera mới mất mạng về sau, cơ chế reconnect xử lý; không cam kết tự rollback sang nguồn cũ đã đóng.

Một số lần runner bị giới hạn thời gian của công cụ sau khi log pytest đã in PASS; các lần đó không dùng để kết luận thành công. Chạy lại với runner riêng đã xác nhận 5 PASS, process thoát, 0 capture session còn sống và chỉ còn MainThread trước khi thoát. Log được giữ trong gói minh chứng.

## Tài liệu kỹ thuật đã đối chiếu

- OpenCV 4.11 video capture properties (open/read timeout, FFmpeg): https://docs.opencv.org/4.11.0/d4/d15/group__videoio__flags__base.html
- FFmpeg RTSP protocol options: https://ffmpeg.org/ffmpeg-protocols.html
- Hikvision RTSP path format: https://supportusa.hikvision.com/support/solutions/articles/17000129022-do-you-have-an-example-showing-the-format-for-getting-a-rtsp-stream-from-a-camera-
