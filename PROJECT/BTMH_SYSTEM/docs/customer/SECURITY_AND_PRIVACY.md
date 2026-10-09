# Bảo mật và riêng tư - bổ sung 5.4.2

Dữ liệu nhận diện, nhân sự và camera vẫn dùng cấu trúc lưu trữ hiện có. Bản vá thêm các bảng sms_*_v542, không reset database.

Số nhận SMS được mã hóa trong database bằng cơ chế khóa hiện có. Cần giữ khóa tương ứng khi backup/restore. Không coi mã hóa là bảo vệ tuyệt đối khi tài khoản Windows/PC đã bị chiếm quyền.

Twilio nhận số điện thoại, yêu cầu gửi và xác minh OTP qua HTTPS; adapter không gửi ảnh/FaceID. SMS là tích hợp trực tuyến bổ sung, không phải tính năng hoàn toàn offline. Chủ sở hữu cần duyệt nhà cung cấp và thông báo cho người dùng trước khi đăng ký số nhận.

OTP không ghi vào log. Chỉ lưu băm mã khôi phục và cookie tin cậy ở database. Các mã khôi phục phải cất riêng và không gửi cùng gói hỗ trợ. API Secret lưu bằng Windows DPAPI theo user; đổi user/máy có thể cần cấu hình lại.

Tin cậy trình duyệt không phải xác minh phần cứng hay chống mã độc. Máy dùng chung không nên bật. Bản vá không cấp chứng nhận tuân thủ pháp luật dữ liệu; cần đánh giá quy trình vận hành và lưu trữ trước khi triển khai thật.
