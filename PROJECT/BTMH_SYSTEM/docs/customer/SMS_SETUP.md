# Thiết lập SMS OTP - Bảo Tín Mạnh Hải 5.4.2

## 1. Cần có trước

Bản này tích hợp **Twilio Verify**, không phải một cổng gửi SMS miễn phí có sẵn. Cần tài khoản nhà cung cấp, Verify Service cấu hình mã 6 số, API Key có quyền phù hợp, quyền gửi đến nơi nhận và hạn mức/tài khoản thanh toán phù hợp. Máy chủ cần Internet khi gửi và kiểm tra OTP. Chưa xác nhận khả năng gửi đến SIM của khách hàng.

Adapter hiện tại chỉ hỗ trợ Twilio Verify. Nếu doanh nghiệp đã có nhà cung cấp SMS khác, phải bổ sung adapter theo API chính thức; không dán URL bất kỳ vào bộ cấu hình này.

## 2. Lưu cấu hình trên PC

Dùng cùng tài khoản Windows chạy phần mềm, nhấp đúp:

`CONG_CU_TUY_CHON/08_CAU_HINH_SMS.bat`

Nhập bốn trường lấy từ tài khoản Twilio của doanh nghiệp: Account SID (AC...), API Key SID (SK...), Verify Service SID (VA...) và API Secret. API Secret được ẩn khi gõ. Xác nhận bằng `LUU`. Khởi động lại phần mềm.

Công cụ lưu bằng Windows DPAPI theo tài khoản Windows, không ghi API Secret rõ ra file. Công cụ **không tự gửi SMS thử**; dòng lưu thành công chỉ xác nhận lưu cấu hình, không chứng minh dịch vụ gửi được. Không gửi API Secret, OTP hay mã khôi phục qua chat/ảnh chụp. Không chạy bằng Administrator.

## 3. Bật SMS cho tài khoản

Đăng nhập tài khoản hiện có, mở **Tài khoản & phân quyền -> Bảo mật tài khoản**. Nhập lại mật khẩu, số điện thoại của chủ tài khoản, chọn bật SMS rồi gửi mã. Nhập mã 6 số thật nhận trên điện thoại để kích hoạt.

Nếu tài khoản đã bật Authenticator/SMS, trước khi đổi phương thức hoặc số điện thoại phải xác minh lại yếu tố hiện có. Authenticator cũ: đăng xuất, đăng nhập và nhập mã; không chỉ dùng chế độ tin cậy khi chuyển đổi. SMS: dùng mục xác minh lại trong Bảo mật tài khoản.

Sau khi kích hoạt, hệ thống hiện **8 mã khôi phục một lần duy nhất**. Lưu ở nơi an toàn, tách khỏi PC chạy phần mềm. Mã khôi phục dùng thay bước hai sau mật khẩu, **không phải chức năng lấy lại mật khẩu đã quên**.

## 4. Đăng nhập hằng ngày

Trình duyệt mới: mật khẩu -> SMS gửi đến số đã xác minh -> nhập OTP -> vào hệ thống. Không cho thay đổi số nhận tại màn hình đăng nhập.

Chỉ trên máy cá nhân được kiểm soát, có thể chọn **Tin cậy trình duyệt này trong 30 ngày**. Tùy chọn không tích sẵn. Các lần sau vẫn nhập mật khẩu, nhưng không phải nhập OTP khi cookie tin cậy còn hạn. Không có nghĩa giữ nguyên phiên đăng nhập 30 ngày.

Hết hạn 30 ngày, xóa cookie, đổi trình duyệt, bị thu hồi, đổi mật khẩu/quyền hay đổi yếu tố xác thực sẽ cần xác minh lại. Không dùng tính năng tin cậy trên máy dùng chung. Có danh sách và nút thu hồi trong Bảo mật tài khoản. Thu hồi chặn lần bỏ qua OTP tiếp theo; không tự đăng xuất phiên đang thao tác.

## 5. Khi mất Internet/SIM

Trình duyệt tin cậy còn hiệu lực: dùng mật khẩu. Trình duyệt mới/hết tin cậy: dùng mật khẩu + một mã khôi phục chưa dùng. Hệ thống **không tự bỏ qua xác minh** khi nhà cung cấp lỗi.

Không còn SIM, mã khôi phục hay phương thức hợp lệ: cần quy trình khôi phục quản trị có kiểm soát. Không chỉnh database để bỏ MFA, không xóa dữ liệu.

## 6. Giới hạn và bảo mật

Phiên xác minh của ứng dụng có hạn 5 phút; gửi lại không gia hạn. Gửi lại cách nhau tối thiểu 60 giây; tối đa 5 lần kiểm tra mỗi phiên. Có hạn mức theo tài khoản/số nhận/IP và toàn hệ thống. Giới hạn của nhà cung cấp có thể chặt hơn. Gửi thất bại cũng tính vào hạn mức chống spam.

Số điện thoại và dữ liệu cần cho xác minh được gửi đến Twilio qua HTTPS. Adapter này không gửi ảnh, video, vector khuôn mặt. Cần phê duyệt việc sử dụng nhà cung cấp bên ngoài trong quy định dữ liệu của doanh nghiệp. SMS không chống lừa đảo/chiếm SIM tuyệt đối; không chia sẻ OTP cho bất kỳ ai.

Bản này cho phép HTTP chỉ trên loopback của PC. Đăng nhập qua LAN cần HTTPS với chứng chỉ và reverse proxy được cấu hình đúng; bản vá **chưa cài tự động HTTPS**. Không mở cổng 8100 ra Internet.

## Tài liệu chính thức đã đối chiếu

- https://www.twilio.com/docs/verify/api/verification
- https://www.twilio.com/docs/verify/api/verification-check
- https://pages.nist.gov/800-63-4/sp800-63b.html

Đối chiếu API không thay thế nghiệm thu gửi và nhận tin nhắn thật.
