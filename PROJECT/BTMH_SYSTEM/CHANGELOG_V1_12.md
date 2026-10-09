# CHANGELOG V1.12.0 – PostgreSQL Offline Production

- Chuyển database production mặc định từ SQLite sang PostgreSQL local/offline.
- Dedicated PostgreSQL service `CampusFacePostgreSQL`, port `55432`, tránh xung đột cổng 5432 của hệ thống khác.
- Role ứng dụng `campusface_app` không có quyền superuser/createdb/createrole.
- Credential PostgreSQL được bảo vệ bằng Windows DPAPI; không ghi password vào module.env.
- Dữ liệu khách hàng mặc định chuyển sang `C:\ProgramData\CampusFace`.
- Cấu hình runtime chuyển sang `C:\ProgramData\CampusFace\config\module.env`.
- Backup production sử dụng `pg_dump`/`pg_restore`; SQLite backup giữ lại cho migration/test mode.
- Thêm migration SQLite -> PostgreSQL, giữ nguyên ID và FaceID encryption key.
- Thêm bộ chuẩn bị PostgreSQL 17.11 offline, xác minh SHA-256 của installer.
- Setup customer chạy quyền Administrator và có thể đóng thành `CampusFace_Setup_V1.12.0.exe`.
- Giữ nguyên Passive Classroom V1.11: không blink/turn/look-at-camera challenge.
- Regression suite: 32/32 PASS trong maintenance SQLite mode.
