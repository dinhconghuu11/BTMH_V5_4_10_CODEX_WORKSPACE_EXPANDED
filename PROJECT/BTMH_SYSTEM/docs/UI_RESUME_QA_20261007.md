# UI tiếp nối — 2026-10-07

Kết quả: **PASS cả 3 mục UI**, tiếp tục từ source hiện tại. Không sửa AI, MediaMTX, FaceID/PAD hoặc database. Đối chiếu SHA-256 của 49 file trực tiếp trong `module_app/`: 0 file thay đổi. Không tạo installer hoặc chạy full regression trong checkpoint UI này.

| Mục | Kết quả | Thay đổi và nguyên nhân |
| --- | --- | --- |
| Bỏ debug overlay | PASS | Media JS không tạo block Native Gateway/Reason/transport trên video; CSS ẩn HUD resolution/FPS/queue cũ. Giữ canvas kết quả nhận diện, thông báo offline và trạng thái/zoom PTZ. Stats/events và lifecycle transport giữ nguyên. |
| Account menu + logout | PASS | Menu hiển thị danh tính/vai trò, action theo quyền, keyboard/focus và đóng theo lifecycle. Logout dùng endpoint hiện có, single flight, deadline 8 giây; lỗi không báo thành công. Thành công/401 mở gate đăng nhập và dọn dữ liệu gate/MFA. Response auth-status cũ bị bỏ qua sau logout hoặc đổi tài khoản. |
| Redesign login/auth | PASS | Tiếp tục setup/login/help/MFA/SMS/recovery hiện có, giữ đủ 41 ID auth cũ. Burgundy/gold/ivory, logo/artwork local, label rõ, live feedback, mobile một cột và cuộn tới action ở màn hình thấp. Chặn submit MFA trùng từ hai Enter handler hiện có. |

File product thay đổi: `frontend/index.html`, `frontend/js/app.js`, `frontend/js/btmh_media_v5410.js`, `frontend/css/btmh_media_v5410.css`; thêm `frontend/css/btmh_account_ui_v550.css` và `frontend/css/btmh_auth_ui_v550.css`. Cache query của app/media được cập nhật. `DESIGN.md` bổ sung checkpoint. Preview helper được sửa để trạng thái admin dùng đúng class `hidden` như ứng dụng.

| Kiểm tra tập trung | Kết quả |
| --- | --- |
| `node tests_browser/auth_account_ui.test.cjs` trong sandbox | **10 PASS, 0 FAIL**: quyền/menu/bàn phím, logout lỗi/thành công/401, single flight, cleanup, submit MFA trùng và auth-status trễ. |
| `node tests_browser/media_lifecycle.test.cjs` trong sandbox | **45 PASS, 0 FAIL**: không có debug DOM/HUD kỹ thuật, vẫn giữ transport, recovery, ownership và cleanup. |
| `node --check frontend/js/app.js` và `node --check frontend/js/btmh_media_v5410.js` | PASS trong sandbox. |
| Compile `tests_browser/preview_ui_v550.py`; syntax `visual_auth_account_v550.cjs` | PASS trong sandbox. |
| Preview tĩnh auth/account bằng Chrome headless | **11 PASS** tại 390/768/1440 px và viewport cao 600 px; CSS loaded, hidden guards, visibility, horizontal overflow, menu bounds và action scroll. Screenshot được xem trực tiếp. Chạy trước yêu cầu mới chỉ dùng sandbox, với profile test riêng đã đóng/xóa. |
| `node --test` runner trong Windows sandbox | **BLOCKED: spawn EPERM**. Hai file test tập trung phía trên đã chạy thành công trực tiếp, không spawn child process. |
| pytest UI trong sandbox | **BLOCKED**: sandbox không đọc được entrypoint pytest (`No module named pytest.__main__`). Không chạy lại ngoài sandbox sau yêu cầu mới. Trước yêu cầu mới, 14 test UI Python đã chạy thành công với quyền được cấp. |

Lần chạy đầu của test account có lỗi regex trong test harness; đã sửa. Test mới cũng tái hiện lỗi auth-status trễ trước khi sửa frontend; lần chạy cuối đạt 10/10. Không có lỗi còn lại trong các kiểm tra tập trung hoàn thành. Full regression và kiểm tra auth server/camera thật không thuộc checkpoint này.

Ảnh và dữ liệu render: `frontend/.qa_preview_v550/` (`login-desktop.png`, `login-mobile.png`, `account-desktop.png`, `account-mobile.png`, các view setup/help/MFA/recovery và `visual-results.json`). Preview không nạp product scripts, không gọi API hoặc camera. Node menu/auth tests dùng mock; không kết luận nghiệm thu đăng nhập/SMS hoặc hardware thật từ preview.

Rủi ro còn lại: CSS chỉ đổi presentation; các tổ hợp viewport/zoom chưa đo có thể cần tinh chỉnh. Logout giữ phiên UI hiện có khi server không xác nhận thu hồi để người dùng thử lại. Không thay quyền, chính sách xác thực hoặc transport.

Rollback source UI: khôi phục `index.html`, `app.js` và `media_lifecycle.test.cjs` từ `backups/CODEX_UI_PRE_RESUME_20261007.zip` về đúng thư mục frontend/tests_browser tương ứng. Archive dùng tên file phẳng. JS/CSS media trong archive này đã được chụp sau thao tác bỏ block transport đầu tiên; để hoàn tác đầy đủ phần media, dùng hai bản gốc chính xác tại `backups/ui_resume_original_media/btmh_media_v5410.js` và `btmh_media_v5410.css`. Bỏ hai stylesheet/test UI mới nếu rollback toàn checkpoint; không khôi phục archive native cũ lên các sửa transport hiện tại. Khởi động lại frontend/reload sau rollback; giữ nguyên database, runtime và credentials.

Sau yêu cầu chỉ chạy sandbox: không có command ngoài sandbox mới, không xin escalation, chỉ hoàn thành focused UI checks. Server preview và Chrome test đã dừng; profile Chrome tạm đã xóa. Dừng công việc tại checkpoint này.
