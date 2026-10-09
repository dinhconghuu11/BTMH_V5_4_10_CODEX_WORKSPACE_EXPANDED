# Architecture Target

## Live video path

```text
Hikvision /101 H.264
        |
        v
MediaMTX / native media gateway
        |
        v
WHEP / WebRTC
        |
        v
Browser <video>
```

The primary Live View must not depend on FaceID/PAD inference finishing.
JPEG/WebSocket/MJPEG/snapshot transports are fallbacks only.

## AI path

```text
Camera / AI stream
       |
       v
Capture worker
       |
       v
Latest-frame scheduling
   +---+---+
   |       |
Detect   PAD / FaceID
   |       |
   +---events/results---+
                       |
                       v
                      UI
```

## Data/config principle
Configured camera records in the database are the canonical source. Example/template camera files must not overwrite an existing operator-configured camera.

## Long-term direction
- `/101` main stream: fullscreen, recording, evidence, best-shot.
- `/102` substream: detection/FaceID/PAD/grid where appropriate.
- AI frame queues should stay bounded/latest-frame oriented.
- Hardware acceleration is optional optimization, not a correctness dependency.
