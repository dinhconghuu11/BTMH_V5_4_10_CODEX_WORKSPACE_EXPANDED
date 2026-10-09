CREATE TABLE IF NOT EXISTS camera_devices (
 id SERIAL PRIMARY KEY,
 name VARCHAR(100),
 type VARCHAR(50),
 ip VARCHAR(64),
 rtsp TEXT,
 username TEXT,
 password TEXT,
 campus VARCHAR(100),
 building VARCHAR(100),
 floor VARCHAR(50),
 room VARCHAR(100),
 enabled BOOLEAN DEFAULT TRUE,
 status VARCHAR(30) DEFAULT 'OFFLINE',
 fps REAL DEFAULT 0,
 latency_ms INTEGER DEFAULT 0,
 last_online TIMESTAMP
);
