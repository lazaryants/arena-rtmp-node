"""Persistent desired state for supervised outgoing restreams."""

import json
import os
import tempfile
import threading
from pathlib import Path


SCHEMA_VERSION = 1


class DesiredRestreamStore:
    """Atomically store which configured destinations should be running."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _validate_pair(field_id, url_index):
        if type(field_id) is not int or not 1 <= field_id <= 16:
            raise ValueError("invalid desired-state field ID")
        if type(url_index) is not int or not 0 <= url_index < 32:
            raise ValueError("invalid desired-state destination index")
        return field_id, url_index

    def load(self):
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except FileNotFoundError:
                return set()

            if not isinstance(data, dict) or set(data) != {
                "schema_version",
                "active",
            }:
                raise ValueError("invalid restream desired-state root")
            if data["schema_version"] != SCHEMA_VERSION:
                raise ValueError("unsupported restream desired-state schema")
            if not isinstance(data["active"], list):
                raise ValueError("restream desired-state active must be a list")

            active = set()
            for item in data["active"]:
                if not isinstance(item, dict) or set(item) != {
                    "field_id",
                    "url_index",
                }:
                    raise ValueError("invalid restream desired-state entry")
                pair = self._validate_pair(
                    item["field_id"],
                    item["url_index"],
                )
                if pair in active:
                    raise ValueError("duplicate restream desired-state entry")
                active.add(pair)
            return active

    def save(self, active):
        normalized = {
            self._validate_pair(field_id, url_index)
            for field_id, url_index in active
        }
        serialized = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "active": [
                    {"field_id": field_id, "url_index": url_index}
                    for field_id, url_index in sorted(normalized)
                ],
            },
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
                directory_fd = os.open(
                    self.path.parent,
                    os.O_RDONLY | os.O_DIRECTORY,
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
        return normalized

    def update(self, pairs, desired):
        pairs = {
            self._validate_pair(field_id, url_index)
            for field_id, url_index in pairs
        }
        with self._lock:
            active = self.load()
            if desired:
                active.update(pairs)
            else:
                active.difference_update(pairs)
            return self.save(active)

    def discard_field(self, field_id):
        self._validate_pair(field_id, 0)
        with self._lock:
            active = {
                pair
                for pair in self.load()
                if pair[0] != field_id
            }
            return self.save(active)
