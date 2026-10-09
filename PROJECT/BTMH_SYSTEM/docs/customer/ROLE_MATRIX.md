# Ma trận phân quyền khách hàng

| Vai trò | Phạm vi sử dụng | Quyền chính | Không được phép |
|---|---|---|---|
| **Chủ sở hữu** | Toàn hệ thống | Toàn quyền; quản trị tài khoản, bảo mật, camera, FaceID, backup, cấu hình | Không cấp đại trà; chỉ tạo qua thiết lập lần đầu |
| **Quản trị viên** | Toàn hệ thống theo ủy quyền | Quản lý tài khoản, vận hành, cấu hình và hỗ trợ kỹ thuật | Không thể tự nâng thành Chủ sở hữu qua giao diện |
| **Quản lý cửa hàng** | Cửa hàng/chi nhánh được giao | Nhân sự, chấm công, camera, sự cố, báo cáo vận hành | Không quản trị tài khoản cấp cao hoặc cấu hình hệ thống toàn cục |
| **Nhân sự** | Dữ liệu nhân viên | Hồ sơ, FaceID, ca làm, chấm công, báo cáo nhân sự | Không xem hoặc điều khiển camera; không cấu hình hệ thống |
| **Giám sát / Bảo vệ** | Camera và an ninh | Camera trực tiếp, xem lại, nhận diện, sự cố và bằng chứng | Không sửa hồ sơ nhân sự hoặc quản trị tài khoản |
| **Nhân viên** | Dữ liệu cá nhân trong ứng dụng nhân viên tương lai | Lịch sử chấm công cá nhân theo quyền `attendance.view.self` | Không truy cập trang quản lý web, không xem người khác, camera hoặc báo cáo tổng hợp |

## Nguyên tắc kỹ thuật

- Quyền được kiểm tra ở backend, không chỉ ẩn menu ở frontend.
- Mọi API trình duyệt riêng tư đều phải khai báo permission trong bản đồ RBAC tập trung; API chưa khai báo quyền bị chặn theo cơ chế fail-closed.
- Trước khi có Chủ sở hữu, tất cả API riêng tư đều bị chặn; chỉ health và luồng thiết lập lần đầu được phép hoạt động.
- Tài khoản Nhân viên đăng nhập vào trang quản lý sẽ bị đăng xuất và nhận hướng dẫn sử dụng ứng dụng nhân viên khi được triển khai.
- Các role legacy vẫn được giữ ở backend để tương thích dữ liệu cũ nhưng không xuất hiện trong giao diện gán quyền thông thường.
