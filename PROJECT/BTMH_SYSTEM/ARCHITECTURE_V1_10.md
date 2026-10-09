# Architecture – V1.10 Production Ready

## Camera / Recognition
Camera Static → Latest Frame → Face Detector → Tracker → Event-driven FaceID → Anti-spoof/Liveness → Check-in decision.

## Classroom
Camera Static → Person/Face Tracking → Track identity cache → Activity trigger → Adaptive Pose/Action → Customer UI (bbox + name + action).

## Attendance
Successful recognition event → Active session lookup by student class/time → Attendance record → PRESENT/LATE. Spoof event → rejected counter only.

## Operations
Local FastAPI + SQLite + local UI. Runtime data is separated from application code. Backup uses SQLite snapshot + FaceID key + module.env.

## RBAC
Local Admin/Operator sessions are in-memory bearer tokens; password hashes remain in SQLite. Admin operations are protected while recognition/check-in remains kiosk-style local operation.
