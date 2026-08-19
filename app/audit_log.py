"""Bounded structured audit log without stream credentials."""

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 3
SENSITIVE_NAME = re.compile(
    r"(password|secret|token|url|key)",
    re.IGNORECASE,
)
RTMP_URL = re.compile(r"rtmps?://\S+", re.IGNORECASE)


class AuditLog:
    """Append and query safe JSON-lines audit records."""

    def __init__(
        self,
        path,
        max_bytes=DEFAULT_MAX_BYTES,
        backup_count=DEFAULT_BACKUP_COUNT,
    ):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.backup_count = int(backup_count)
        self._lock = threading.Lock()

    @staticmethod
    def _safe_text(value, maximum=160):
        text = str(value or "")
        text = RTMP_URL.sub("[redacted]", text)
        return text[:maximum]

    @classmethod
    def _safe_mapping(cls, values):
        if not isinstance(values, dict):
            return {}
        safe = {}
        for name, value in values.items():
            name = cls._safe_text(name, 48)
            if not name or SENSITIVE_NAME.search(name):
                continue
            if isinstance(value, bool):
                safe[name] = value
            elif isinstance(value, (int, float)):
                safe[name] = value
            elif value is not None:
                safe[name] = cls._safe_text(value)
        return safe

    def _rotate_if_needed(self, incoming_size):
        try:
            current_size = self.path.stat().st_size
        except OSError:
            current_size = 0
        if current_size + incoming_size <= self.max_bytes:
            return

        oldest = self.path.with_name(
            f"{self.path.name}.{self.backup_count}"
        )
        try:
            oldest.unlink()
        except FileNotFoundError:
            pass

        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            try:
                os.replace(source, target)
            except FileNotFoundError:
                pass

        try:
            os.replace(
                self.path,
                self.path.with_name(f"{self.path.name}.1"),
            )
        except FileNotFoundError:
            pass

    def append(
        self,
        *,
        actor,
        role,
        action,
        outcome,
        target=None,
        details=None,
    ):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": self._safe_text(actor, 64) or "anonymous",
            "role": self._safe_text(role, 16) or "anonymous",
            "action": self._safe_text(action, 80),
            "outcome": (
                "success" if outcome == "success" else "failure"
            ),
            "target": self._safe_mapping(target),
            "details": self._safe_mapping(details),
        }
        encoded = (
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._rotate_if_needed(len(encoded))
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_APPEND | os.O_CREAT,
                0o600,
            )
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.chmod(self.path, 0o600)

    def _paths(self):
        paths = [self.path]
        paths.extend(
            self.path.with_name(f"{self.path.name}.{index}")
            for index in range(1, self.backup_count + 1)
        )
        return paths

    @staticmethod
    def _parse_time(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError:
            raise ValueError("Invalid audit time filter")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def recent(
        self,
        *,
        limit=200,
        actor=None,
        action=None,
        outcome=None,
        since=None,
        until=None,
    ):
        limit = max(1, min(int(limit), 500))
        actor_filter = self._safe_text(actor, 64).lower()
        action_filter = self._safe_text(action, 80).lower()
        outcome_filter = self._safe_text(outcome, 16).lower()
        since_time = self._parse_time(since)
        until_time = self._parse_time(until)
        records = []

        for path in self._paths():
            try:
                lines = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record_time = self._parse_time(
                    record.get("timestamp")
                )
                if since_time and (
                    record_time is None or record_time < since_time
                ):
                    continue
                if until_time and (
                    record_time is None or record_time > until_time
                ):
                    continue
                if (
                    actor_filter
                    and actor_filter not in str(
                        record.get("actor", "")
                    ).lower()
                ):
                    continue
                if (
                    action_filter
                    and action_filter not in str(
                        record.get("action", "")
                    ).lower()
                ):
                    continue
                if (
                    outcome_filter
                    and outcome_filter != str(
                        record.get("outcome", "")
                    ).lower()
                ):
                    continue
                records.append(record)
                if len(records) >= limit:
                    return records
        return records
