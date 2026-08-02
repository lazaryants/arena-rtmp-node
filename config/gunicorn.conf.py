"""Production Gunicorn settings for Restream Manager."""

import os


bind = os.environ.get(
    "CRICKET_RTMP_MANAGER_BIND",
    "127.0.0.1:5000",
)

# Restream Manager controls shared configuration, PID files and FFmpeg
# processes. Multiple workers would introduce concurrent writers and
# inconsistent in-memory process state.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("CRICKET_RTMP_MANAGER_THREADS", "4"))

timeout = int(os.environ.get("CRICKET_RTMP_MANAGER_TIMEOUT", "30"))
graceful_timeout = 15
keepalive = 5

accesslog = "-"
errorlog = "-"
capture_output = True
loglevel = os.environ.get("CRICKET_RTMP_LOG_LEVEL", "info")

proc_name = "cricket-rtmp-manager"
