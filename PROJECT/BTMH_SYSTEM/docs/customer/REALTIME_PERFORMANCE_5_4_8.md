# Realtime Performance 5.4.8

Bản 5.4.8 giữ nguyên mô hình FaceID/PAD và chỉ tối ưu đường realtime của camera IP.

## Profile mặc định

`balanced` dành cho laptop/PC phổ thông:

- Camera Hikvision vẫn phát H.264 theo cấu hình của camera.
- Backend lấy tối đa 18 frame/giây và tối đa 1280 px chiều ngang trước khi đưa frame thô vào Python.
- FaceID/PAD lấy frame mới nhất, mục tiêu 7 FPS / 960 px; không xếp hàng frame cũ.
- Preview web mục tiêu 15 FPS / tối đa 1280 px / JPEG 78.
- USB/laptop camera giữ hành vi cũ.

Có thể chọn `BTMH_RTSP_REALTIME_PROFILE=quality` trên PC mạnh hoặc `light` trên PC yếu. Không profile nào thay ngưỡng nhận diện, model FaceID hay model PAD.

## Tiêu chí nghiệm thu

- Web không tích lũy độ trễ theo thời gian.
- `queue_depth` luôn bằng 0 trong telemetry.
- AI có thể bỏ frame cũ khi tải cao nhưng luôn lấy frame mới nhất.
- Camera/IP/FaceID/PAD tiếp tục hoạt động khi chuyển module.
