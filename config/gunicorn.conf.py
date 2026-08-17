"""Production Gunicorn settings for Restream Manager."""

import os


bind = os.environ.get(
    "ARENA_RTMP_MANAGER_BIND",
    "127.0.0.1:5000",
)

# Configuration writes are serialized inside the manager. A single worker
# keeps that application-level serialization local and predictable; outgoing
# FFmpeg processes are owned by the separate supervisor service.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("ARENA_RTMP_MANAGER_THREADS", "4"))

timeout = int(os.environ.get("ARENA_RTMP_MANAGER_TIMEOUT", "30"))
graceful_timeout = 15
keepalive = 5

accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.environ.get("ARENA_RTMP_LOG_LEVEL", "info")

proc_name = "arena-rtmp-manager"
