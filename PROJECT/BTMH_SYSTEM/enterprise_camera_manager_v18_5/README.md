# CampusFace V18.5 Enterprise Camera Manager

Mục tiêu:
- Camera profile thay cho camera hard-code.
- Sẵn sàng quản lý Hikvision RTSP, USB camera, PTZ ONVIF.
- Chuẩn bị chuyển profile sang PostgreSQL.

Luồng:
Camera Profile -> Camera Worker -> Frame Buffer -> AI Core

Giai đoạn tiếp theo:
- UI Add Camera
- PostgreSQL camera_devices
- Health monitoring
- Multi camera scheduler
