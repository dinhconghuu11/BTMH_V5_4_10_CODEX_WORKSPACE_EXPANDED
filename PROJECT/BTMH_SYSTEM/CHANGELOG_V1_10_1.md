# CampusFace V1.10.1 – Tab Stable / UI Polish

Bản vá tập trung vào lỗi chuyển tab làm trạng thái liveness/anti-spoof bị đỏ và hoàn thiện banner Tổng quan.

## Sửa nhận diện khi chuyển tab
- Giữ cùng hệ tọa độ AI của FaceID khi bật/tắt Classroom; không đổi 1280 ↔ 960 cho tracker nhận diện.
- Nếu nguồn camera thực sự đổi kích thước, tracker đang sống được rescale thay vì tạo người/track mới.
- Timeout của thử thách liveness khi không có bằng chứng màn hình/ảnh không còn bị kết luận ngay là `SPOOF_BLOCKED`; hệ thống chuyển về `CHECKING` và xác minh lại.
- `SPOOF_BLOCKED` vẫn được giữ cho bằng chứng carrier màn hình/ảnh mạnh qua nhiều frame.
- Khi đổi trang, UI nhận diện xóa trạng thái cảnh báo tạm cũ trước khi hiển thị trạng thái mới.

## Giao diện
- Tiêu đề `Đăng ký & nhận diện khuôn mặt bằng camera tĩnh` nằm một hàng trên desktop.
- Responsive vẫn cho phép xuống dòng trên màn hình nhỏ để không tràn bố cục.

## Cài đặt Windows
- `START_HERE/SETUP_AND_START` ưu tiên Python 3.12 đã có trên máy trước khi chạy private installer.
- `INSTALL_CURRENT_PC_WINDOWS.bat` dùng `vendor\wheels` offline nếu bundle đã được chuẩn bị.
- Private Python installer có log `logs\python_install.log` và fallback sang Python 3.12 hiện có.
