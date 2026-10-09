import threading
from .profile_store import CameraProfileStore
from ..enterprise.camera_worker import CameraWorker

class CameraManagerV18:
    def __init__(self):
        self.store = CameraProfileStore()
        self.workers = {}
        self.lock = threading.Lock()

    def load(self):
        for profile in self.store.list_enabled():
            self.add(profile)

    def add(self, profile):
        with self.lock:
            cid = profile['id']
            if cid in self.workers:
                return
            worker = CameraWorker(profile)
            self.workers[cid] = worker
            worker.start()

    def health(self):
        return {cid:{
            'name':w.profile.get('name',''),
            'online':w.status.online,
            'fps':round(w.status.fps,2),
            'latency_ms':round(w.status.latency_ms,2),
            'reconnect':w.status.reconnect
        } for cid,w in self.workers.items()}
