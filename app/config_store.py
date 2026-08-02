"""Validated and atomic storage for the node configuration."""

import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse


FIELD_ID_RE = re.compile(r"(?:[1-9]|1[0-6])\Z")
STREAM_KEY_RE = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
ALLOWED_FIELD_KEYS = {
    "emoji",
    "enabled",
    "hls_url",
    "key",
    "name",
    "publish_auth_enabled",
    "restream_url",
    "restream_urls",
    "rtmp_url",
    "stream_key",
}


class ConfigValidationError(ValueError):
    """Configuration data does not match the supported schema."""


def require_text(value, label, maximum, allow_empty=False):
    if not isinstance(value, str):
        raise ConfigValidationError(f"{label} must be a string")
    if not allow_empty and not value:
        raise ConfigValidationError(f"{label} must not be empty")
    if len(value) > maximum:
        raise ConfigValidationError(f"{label} is too long")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ConfigValidationError(f"{label} contains control characters")


def validate_rtmp_url(value, label):
    require_text(value, label, 2048)
    if any(character.isspace() for character in value):
        raise ConfigValidationError(f"{label} contains whitespace")
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
    except ValueError as error:
        raise ConfigValidationError(f"{label} is invalid") from error
    if parsed.scheme not in {"rtmp", "rtmps"} or not hostname:
        raise ConfigValidationError(f"{label} must be an RTMP or RTMPS URL")


def validate_field(field_id, field):
    if not isinstance(field, dict):
        raise ConfigValidationError(f"field {field_id} must be an object")

    unknown = set(field) - ALLOWED_FIELD_KEYS
    if unknown:
        raise ConfigValidationError(
            f"field {field_id} contains unsupported keys: {sorted(unknown)}"
        )

    for key in ("enabled", "publish_auth_enabled"):
        if key in field and type(field[key]) is not bool:
            raise ConfigValidationError(f"field {field_id}.{key} must be boolean")

    if "name" in field:
        require_text(field["name"], f"field {field_id}.name", 200)
    if "emoji" in field:
        require_text(field["emoji"], f"field {field_id}.emoji", 32, allow_empty=True)

    stream_key = field.get("stream_key")
    if stream_key is not None and (
        not isinstance(stream_key, str) or not STREAM_KEY_RE.fullmatch(stream_key)
    ):
        raise ConfigValidationError(
            f"field {field_id}.stream_key must match {STREAM_KEY_RE.pattern}"
        )

    publish_key = field.get("key")
    if publish_key is not None:
        require_text(publish_key, f"field {field_id}.key", 512)
    if field.get("publish_auth_enabled") is True and not publish_key:
        raise ConfigValidationError(
            f"field {field_id}.key is required when publish auth is enabled"
        )

    if "hls_url" in field:
        hls_url = field["hls_url"]
        require_text(hls_url, f"field {field_id}.hls_url", 2048)
        if not hls_url.startswith("/hls/") or any(
            character.isspace() for character in hls_url
        ):
            raise ConfigValidationError(
                f"field {field_id}.hls_url must be a relative /hls/ URL"
            )

    for key in ("rtmp_url", "restream_url"):
        if key in field:
            validate_rtmp_url(field[key], f"field {field_id}.{key}")

    destinations = field.get("restream_urls", [])
    if not isinstance(destinations, list):
        raise ConfigValidationError(f"field {field_id}.restream_urls must be a list")
    if len(destinations) > 32:
        raise ConfigValidationError(f"field {field_id}.restream_urls has too many entries")
    for index, destination in enumerate(destinations):
        validate_rtmp_url(
            destination,
            f"field {field_id}.restream_urls[{index}]",
        )


def validate_config(config):
    if not isinstance(config, dict):
        raise ConfigValidationError("configuration root must be an object")
    if set(config) != {"fields"}:
        raise ConfigValidationError("configuration root must contain only fields")

    fields = config["fields"]
    if not isinstance(fields, dict):
        raise ConfigValidationError("fields must be an object")
    if len(fields) > 16:
        raise ConfigValidationError("no more than 16 fields are supported")

    for field_id, field in fields.items():
        if not isinstance(field_id, str) or not FIELD_ID_RE.fullmatch(field_id):
            raise ConfigValidationError(f"invalid field ID: {field_id!r}")
        validate_field(field_id, field)

    return config


def load_and_validate_config(path):
    path = Path(path)
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    return validate_config(config)


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self):
        with self._lock:
            return load_and_validate_config(self.path)

    @contextmanager
    def locked(self):
        """Serialize a complete read-modify-write transaction."""
        with self._lock:
            yield

    def save(self, config):
        validate_config(config)
        serialized = json.dumps(
            config,
            ensure_ascii=False,
            indent=4,
        ) + "\n"

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as file:
                    temporary_path = Path(file.name)
                    file.write(serialized)
                    file.flush()
                    os.fsync(file.fileno())

                temporary_path.chmod(0o600)
                os.replace(temporary_path, self.path)
                temporary_path = None

                directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()

        return config
