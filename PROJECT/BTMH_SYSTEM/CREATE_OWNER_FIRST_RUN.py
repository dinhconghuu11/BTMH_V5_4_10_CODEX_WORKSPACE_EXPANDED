"""Local, explicit fallback for creating the first BTMH owner account.

Run only on the central PC after the database has been installed. This script
never writes the plaintext password to disk and cannot run without a human at
an interactive terminal.
"""
from __future__ import annotations
import getpass
import os
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def fail(message: str, code: int=1) -> None:
    print(f"ERROR: {message}")
    raise SystemExit(code)

if not sys.stdin.isatty():
    fail("First-run owner creation requires an interactive local terminal.")
username=input("Tên đăng nhập Chủ sở hữu: ").strip()
if not re.fullmatch(r"[A-Za-z0-9_.-]{4,64}",username):
    fail("Tên đăng nhập phải dài 4-64 ký tự và chỉ gồm chữ, số, _, ., -.")
password=getpass.getpass("Mật khẩu mới (tối thiểu 12 ký tự): ")
confirm=getpass.getpass("Nhập lại mật khẩu: ")
if password != confirm:
    fail("Hai mật khẩu không trùng nhau.")
if len(password) < 12 or not re.search(r"[A-Z]",password) or not re.search(r"[a-z]",password) or not re.search(r"\d",password):
    fail("Mật khẩu phải có ít nhất 12 ký tự, gồm chữ hoa, chữ thường và chữ số.")
try:
    from argon2 import PasswordHasher
except Exception as exc:
    fail(f"Thiếu Argon2 dependency: {exc}")
password_hash=PasswordHasher().hash(password)
# Plaintext is no longer needed.
del password, confirm
os.environ["BTMH_ALLOW_FIRST_RUN_OWNER"]="1"
from module_app import auth
auth._RELEASE_OWNER_USERNAME=username
auth._RELEASE_OWNER_PASSWORD_HASH=password_hash
result=auth.provision_release_owner_account()
if result is False:
    fail("Không tạo được tài khoản. Hãy kiểm tra database và log cài đặt.")
print("Đã tạo/cập nhật tài khoản Chủ sở hữu bằng mật khẩu do Hữu nhập.")
print("Hãy đăng nhập, bật MFA và cất recovery code ở nơi an toàn.")
