from .camera_worker import CameraWorker

class EnterpriseCameraManager:
    def __init__(self):
        self.workers = {}

    def add_camera(self, profile):
        worker = CameraWorker(profile)
        self.workers[profile.camera_id] = worker
        worker.start()

    def remove_camera(self, camera_id):
        if camera_id in self.workers:
            self.workers[camera_id].stop()
            del self.workers[camera_id]

    def health(self):
        return {
            cid: {
                'name': w.profile.name,
                'online': w.status.online,
                'fps': round(w.status.fps,2),
                'latency_ms': round(w.status.latency_ms,2),
                'reconnect': w.status.reconnect,
            }
            for cid,w in self.workers.items()
        }
