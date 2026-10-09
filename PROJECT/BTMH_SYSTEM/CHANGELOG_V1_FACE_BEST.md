# CampusFace V1 FACE - Best Recognition

## Recognition / anti-spoof core
- Added a dedicated MiniFASNet V2 ONNX passive presentation-attack detector before FaceID.
- Multi-frame PAD fusion: PASS requires repeated live evidence; BLOCK requires repeated spoof evidence unless an explicit phone/tablet containment detector fires.
- Removed geometry-only hard blocking. Classroom backgrounds, chair edges and windows can only hold a track in CHECKING.
- PASS remains revocable on later frames.
- FaceID runs only after PAD PASS.

## Identity stability
- Template ranking now combines best template, top-3 template mean and centroid similarity.
- FaceID uses stronger one-shot acceptance and multi-frame consensus for normal cases.
- UNKNOWN is delayed so angled/crouched classroom faces receive more usable frames.

## Runtime
- No active liveness challenge. Students never need to blink, turn, stop, or look at the camera.
- PostgreSQL/runtime architecture from the stable V1.14.x line is preserved.
- PAD model is SHA256 verified by the installer.
