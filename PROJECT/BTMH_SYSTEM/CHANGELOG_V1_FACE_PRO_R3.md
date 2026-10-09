# CampusFace V1 FACE PRO R3 hotfix

- Fixed Recognition page profile panel getting stuck at **Sẵn sàng** while the live camera overlay already showed a recognized FaceID.
- The Recognition page now synchronizes directly from the current recognized live track, even when the corresponding event was already consumed on Dashboard before entering the page.
- Live-track UI refresh no longer creates duplicate history rows.
- Improved FaceID enrollment webcam preview with conservative luminance enhancement and unsharp masking.
- Enrollment preview JPEG quality is raised to at least 90 while the biometric AI/PAD pipeline continues to use the untouched camera frame.
