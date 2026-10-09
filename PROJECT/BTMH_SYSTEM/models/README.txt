BTMH V5.4.10 production AI models

Required FaceID models are installed/recovered into the per-user data models folder:
- face_detection_yunet_2023mar.onnx
- face_recognition_sface_2021dec.onnx

Context anti-spoof:
- The built-in OpenCV full-frame carrier detector is always available and requires no extra download.
- Optional: place yolo11n.pt in the per-user models folder if an Ultralytics runtime is intentionally provisioned. V1 FACE will use it as an additional device detector, but it is not required for install/start.
V1 FACE Best Recognition also uses:
- minifasnet_v2.onnx
  Purpose: passive presentation-attack detection (live / print / replay) before FaceID.
  Mandatory for production and complete offline deployment.
  Acquired yakhyo export SHA256:
  b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907
  Supported alternate variant SHA256:
  d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b
  Variant-specific preprocessing and PAD fail-closed behavior are preserved.
  Exact export/upstream license notices and redistribution review are required;
  an Apache-2.0 label alone does not certify the final customer payload.
