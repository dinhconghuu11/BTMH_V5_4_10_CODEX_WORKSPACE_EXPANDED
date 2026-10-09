# BTMH V5.4.10 - Codex Workspace Expanded

Đây là workspace dành cho VS Code + Codex, tách riêng khỏi gói Easy Install.

## Mở dự án

1. Giải nén toàn bộ ZIP ra một thư mục mới, ví dụ `C:\BTMH_CODEX_5410`.
2. Mở VS Code.
3. Chọn **File > Open Workspace from File...**.
4. Mở `BTMH_V5_4_10_CODEX.code-workspace`.
5. Trong Codex, yêu cầu đọc `AGENTS.md` và `00_START_HERE/README_CODEX.md` trước khi sửa code.

## Source chính

Code thật để chỉnh sửa nằm trong:

`PROJECT/BTMH_SYSTEM/`

Các thư mục `01_BACKEND` ... `10_INSTALLER` ở cấp ngoài là bản đồ điều hướng, không phải bản sao code.

## Quy tắc quan trọng

- Không đưa mật khẩu camera, owner password, token SMS, API key hay RTSP URI có credential vào source/log/tài liệu.
- Không tự ý thay model FaceID/PAD, threshold nhận diện hoặc anti-spoof nếu yêu cầu không liên quan.
- Giữ nguyên định hướng local-first/offline sau cài đặt.
- Sau sửa lớn, chạy test liên quan và `VERIFY_RELEASE.py`.
