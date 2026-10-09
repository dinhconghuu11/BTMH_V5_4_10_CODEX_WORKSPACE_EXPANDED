from __future__ import annotations
import cv2
import threading
import time
from dataclasses import dataclass, field

@dataclass
class CameraStatus:
    online: bool = False
    fps: float = 0.0
    latency_ms: float = 0.0
    reconnect: int = 0
    error: str = ""

class CameraWorker:
    def __init__(self, profile):
        self.profile = profile
        self.status = CameraStatus()
        self.frame = None
        self.stop_event = threading.Event()
        self.thread = None
        self.cap = None
        self.last_time = time.time()

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def connect(self):
        source = self.profile.source
        self.cap = cv2.VideoCapture(source)
        if self.cap.isOpened():
            self.status.online = True
            return True
        self.status.online = False
        return False

    def run(self):
        while not self.stop_event.is_set():
            if self.cap is None or not self.cap.isOpened():
                self.status.reconnect += 1
                self.connect()
                time.sleep(2)
                continue
            t = time.time()
            ok, frame = self.cap.read()
            if ok:
                self.frame = frame
                self.status.online = True
                self.status.latency_ms = (time.time()-t)*1000
                now = time.time()
                self.status.fps = 1/max(now-self.last_time,0.001)
                self.last_time = now
            else:
                self.status.online = False
                self.cap.release()

    def stop(self):
        self.stop_event.set()
        if self.cap:
            self.cap.release()
