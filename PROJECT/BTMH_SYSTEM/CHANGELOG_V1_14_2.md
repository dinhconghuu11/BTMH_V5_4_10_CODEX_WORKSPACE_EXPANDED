# CampusFace V1.14.3

- Fixes installer failure when GitHub model download times out (WinError 10060).
- Recovers verified YuNet/SFace models from previous CampusFace installations and C:\FACE.
- Adds multiple download mirrors (KDE, Hugging Face, GitHub fallback).
- Verifies exact SHA256 and file size to reject HTML pages, Git LFS pointer files, and corrupt downloads.
- Uses isolated per-user data root: `%LOCALAPPDATA%\CampusFaceV1142`.
