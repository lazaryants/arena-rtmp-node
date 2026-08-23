"""Central filesystem and network settings for the RTMP node."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def environment_path(name, default):
    return Path(os.environ.get(name, default)).expanduser()


def environment_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def environment_place_ids(name):
    value = os.environ.get(name, "").strip()
    if not value:
        return ()

    place_ids = []
    for item in value.split(","):
        try:
            place_id = int(item.strip())
        except ValueError as error:
            raise ValueError(
                f"{name} must contain comma-separated place numbers"
            ) from error
        if not 1 <= place_id <= 16:
            raise ValueError(f"{name} places must be between 1 and 16")
        if place_id not in place_ids:
            place_ids.append(place_id)
    return tuple(place_ids)


@dataclass(frozen=True)
class Settings:
    project_root: Path = field(
        default_factory=lambda: environment_path(
            "ARENA_RTMP_ROOT",
            "/opt/arena-rtmp-node",
        ),
    )
    public_host: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_PUBLIC_HOST",
            "rtmp.arena76.top",
        ),
    )
    hls_root: Path = field(
        default_factory=lambda: environment_path(
            "ARENA_RTMP_HLS_ROOT",
            "/var/www/hls",
        ),
    )
    ffmpeg_bin: Path = field(
        default_factory=lambda: environment_path(
            "ARENA_RTMP_FFMPEG",
            "/usr/bin/ffmpeg",
        ),
    )
    local_hls_origin: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_LOCAL_HLS_ORIGIN",
            "http://127.0.0.1/hls",
        ).rstrip("/"),
    )
    local_rtmp_origin: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_LOCAL_RTMP_ORIGIN",
            "rtmp://127.0.0.1",
        ).rstrip("/"),
    )
    rtmp_stat_url: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_STAT_URL",
            "http://127.0.0.1:8090/stat",
        ),
    )
    mediamtx_api_url: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_MEDIAMTX_API_URL",
            "http://127.0.0.1:9997",
        ).rstrip("/"),
    )
    mediamtx_hls_places: tuple = field(
        default_factory=lambda: environment_place_ids(
            "ARENA_RTMP_MEDIAMTX_HLS_PLACES",
        ),
    )
    rbac_enabled: bool = field(
        default_factory=lambda: environment_flag(
            "ARENA_RTMP_RBAC_ENABLED",
            False,
        ),
    )
    session_secret: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_SESSION_SECRET",
            "",
        ),
    )
    auth_bind: str = field(
        default_factory=lambda: os.environ.get(
            "ARENA_RTMP_AUTH_BIND",
            "127.0.0.1:8080",
        ),
    )

    @property
    def auth_address(self):
        host, separator, port_text = self.auth_bind.rpartition(":")
        if not separator or not host:
            raise ValueError("ARENA_RTMP_AUTH_BIND must use host:port")
        try:
            port = int(port_text)
        except ValueError as error:
            raise ValueError(
                "ARENA_RTMP_AUTH_BIND port must be an integer"
            ) from error
        if not 1 <= port <= 65535:
            raise ValueError(
                "ARENA_RTMP_AUTH_BIND port must be between 1 and 65535"
            )
        return host, port

    @property
    def app_dir(self):
        return self.project_root / "app"

    @property
    def template_dir(self):
        return self.app_dir / "templates"

    @property
    def config_file(self):
        configured = os.environ.get("ARENA_RTMP_CONFIG")
        return Path(configured) if configured else (
            self.project_root / "state" / "restream-config.json"
        )

    @property
    def users_file(self):
        configured = os.environ.get("ARENA_RTMP_USERS_FILE")
        return Path(configured) if configured else (
            self.project_root / "state" / "users.json"
        )

    @property
    def audit_file(self):
        configured = os.environ.get("ARENA_RTMP_AUDIT_FILE")
        return Path(configured) if configured else (
            self.project_root / "state" / "audit.jsonl"
        )

    @property
    def run_dir(self):
        configured = os.environ.get("ARENA_RTMP_RUN_DIR")
        return Path(configured) if configured else self.project_root / "run"

    @property
    def log_dir(self):
        configured = os.environ.get("ARENA_RTMP_LOG_DIR")
        return Path(configured) if configured else self.project_root / "logs"

    @property
    def supervisor_socket(self):
        configured = os.environ.get("ARENA_RTMP_SUPERVISOR_SOCKET")
        return Path(configured) if configured else self.run_dir / "supervisor.sock"

    def pid_file(self, field_id, url_index):
        return self.run_dir / f"restream_field{field_id}_{url_index}.pid"

    def log_file(self, field_id, url_index):
        return self.log_dir / f"restream_field{field_id}_{url_index}.log"

    def progress_file(self, field_id, url_index):
        return self.run_dir / f"restream_field{field_id}_{url_index}.progress"

    def ensure_runtime_directories(self):
        self.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)


SETTINGS = Settings()
