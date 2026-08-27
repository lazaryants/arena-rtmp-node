"""Dedicated owner of outgoing FFmpeg restream processes."""

import json
import os
import signal
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

import psutil

from .config_store import load_and_validate_config
from .restream_state import DesiredRestreamStore
from .settings import SETTINGS


MAX_REQUEST_SIZE = 4096
RETRY_DELAYS = (5, 10, 20, 30, 60)
MONITOR_INTERVAL = 2
SOURCE_RETRY_DELAY = 10
HEALTHY_RESET_SECONDS = 60
ATTEMPT_WINDOW_SECONDS = 600
MAX_ATTEMPTS_PER_WINDOW = 10
CIRCUIT_COOLDOWN_SECONDS = 300


class RestreamSupervisor:
    def __init__(
        self,
        settings=SETTINGS,
        clock=time.monotonic,
        desired_store=None,
    ):
        self.settings = settings
        self.clock = clock
        self.lock = threading.RLock()
        desired_path = getattr(settings, "desired_restreams_file", None)
        if not isinstance(desired_path, (str, os.PathLike)):
            desired_path = SETTINGS.desired_restreams_file
        self.desired = desired_store or DesiredRestreamStore(desired_path)
        self.recovery = {}

    def fields(self):
        return load_and_validate_config(self.settings.config_file).get("fields", {})

    def process(self, field_id, url_index):
        pid_file = self.settings.pid_file(field_id, url_index)
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            process = psutil.Process(pid)
            if process.is_running() and "ffmpeg" in process.name().lower():
                return process
        except (
            FileNotFoundError,
            ValueError,
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass
        if pid_file.exists():
            pid_file.unlink()
        return None

    def selected_indices(self, field_id, url_index):
        field = self.fields().get(str(field_id))
        if not isinstance(field, dict):
            raise ValueError("field not found")
        destinations = field.get("restream_urls", [])
        if url_index is None:
            return field, list(range(len(destinations)))
        if type(url_index) is not int or not 0 <= url_index < len(destinations):
            raise ValueError("invalid destination index")
        return field, [url_index]

    def source_url(self, field_id, stream_key):
        """Return the local MediaMTX source without HLS latency."""
        return f"{self.settings.local_rtmp_origin}/place{field_id}"

    def source_ready(self, field_id):
        request = urllib.request.Request(
            f"{self.settings.mediamtx_api_url}/v3/paths/get/place{field_id}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                data = json.load(response)
        except (
            OSError,
            ValueError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ):
            return False
        return data.get("ready") is True

    def ffmpeg_command(self, source, destination, progress_file):
        command = [
            str(self.settings.ffmpeg_bin),
            "-hide_banner", "-loglevel", "warning", "-nostats",
            "-stats_period", "1", "-progress", str(progress_file),
            "-i", source,
        ]
        audio_mode = destination["audio_mode"]
        if audio_mode == "source":
            command.extend(["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy"])
        elif audio_mode == "silent":
            command.extend([
                "-f", "lavfi", "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                "-ac", "2", "-shortest",
            ])
        elif audio_mode == "none":
            command.extend(["-map", "0:v:0", "-c:v", "copy", "-an"])
        else:
            raise ValueError("unsupported audio mode")
        command.extend([
            "-f", "flv", "-flvflags", "no_duration_filesize",
            destination["url"],
        ])
        return command

    def _start_selected(self, field_id, field, indices):
        self.settings.ensure_runtime_directories()
        destinations = field.get("restream_urls", [])
        stream_key = field.get("stream_key") or f"stream{field_id}"
        source = self.source_url(field_id, stream_key)
        started = []
        already_running = []
        for index in indices:
            if self.process(field_id, index) is not None:
                already_running.append(index)
                continue
            log_file = self.settings.log_file(field_id, index)
            progress_file = self.settings.progress_file(field_id, index)
            if progress_file.exists():
                progress_file.unlink()
            log_fd = os.open(
                log_file,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            os.chmod(log_file, 0o600)
            log_handle = os.fdopen(
                log_fd, "a", encoding="utf-8", buffering=1,
            )
            try:
                log_handle.write(
                    f"\n=== Restream started at "
                    f"{datetime.now(timezone.utc).isoformat()} ===\n"
                )
                log_handle.write(f"Source: {source}\n")
                log_handle.write("Destination: [configured]\n")
                log_handle.write(
                    f"Audio mode: {destinations[index]['audio_mode']}\n"
                )
                log_handle.flush()
                process = subprocess.Popen(
                    self.ffmpeg_command(source, destinations[index], progress_file),
                    stdout=log_handle,
                    stderr=log_handle,
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                )
            finally:
                log_handle.close()
            pid_file = self.settings.pid_file(field_id, index)
            pid_file.write_text(str(process.pid), encoding="utf-8")
            pid_file.chmod(0o600)
            started.append(index)
        return {
            "success": bool(started) or bool(already_running),
            "message": "restream start processed",
            "started": started,
            "already_running": already_running,
        }

    def start(self, field_id, url_index=None):
        with self.lock:
            field, indices = self.selected_indices(field_id, url_index)
            self.desired.update(
                {(field_id, index) for index in indices},
                True,
            )
            return self._start_selected(field_id, field, indices)

    def _stop_selected(self, field_id, indices):
        stopped = []
        not_running = []
        for index in indices:
            process = self.process(field_id, index)
            if process is None:
                not_running.append(index)
                continue
            process.terminate()
            try:
                process.wait(timeout=10)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            pid_file = self.settings.pid_file(field_id, index)
            if pid_file.exists():
                pid_file.unlink()
            progress_file = self.settings.progress_file(field_id, index)
            if progress_file.exists():
                progress_file.unlink()
            stopped.append(index)
        return {
            "success": True,
            "message": "restream stop processed",
            "stopped": stopped,
            "not_running": not_running,
        }

    def stop(self, field_id, url_index=None):
        with self.lock:
            _, indices = self.selected_indices(field_id, url_index)
            pairs = {(field_id, index) for index in indices}
            self.desired.update(pairs, False)
            for pair in pairs:
                self.recovery.pop(pair, None)
            return self._stop_selected(field_id, indices)

    def restart(self, field_id, url_index=None):
        with self.lock:
            field, indices = self.selected_indices(field_id, url_index)
            pairs = {(field_id, index) for index in indices}
            self.desired.update(pairs, True)
            for pair in pairs:
                self.recovery.pop(pair, None)
            self._stop_selected(field_id, indices)
            return self._start_selected(field_id, field, indices)

    def delete_destination(self, field_id, url_index):
        """Stop a field and remove its desired state before deletion."""
        with self.lock:
            field, _ = self.selected_indices(field_id, url_index)
            destination_count = len(field.get("restream_urls", []))
            self.desired.discard_field(field_id)
            for pair in list(self.recovery):
                if pair[0] == field_id:
                    self.recovery.pop(pair, None)
            self._stop_selected(field_id, range(destination_count))
            deleted_log = self.settings.log_file(field_id, url_index)
            if deleted_log.exists():
                deleted_log.unlink()
            deleted_progress = self.settings.progress_file(field_id, url_index)
            if deleted_progress.exists():
                deleted_progress.unlink()
            for index in range(url_index + 1, destination_count):
                old_log = self.settings.log_file(field_id, index)
                new_log = self.settings.log_file(field_id, index - 1)
                if old_log.exists():
                    os.replace(old_log, new_log)
                old_progress = self.settings.progress_file(field_id, index)
                new_progress = self.settings.progress_file(field_id, index - 1)
                if old_progress.exists():
                    os.replace(old_progress, new_progress)
            return {"success": True, "message": "destination runtime state removed"}

    def _recovery_record(self, pair):
        return self.recovery.setdefault(pair, {
            "failure_count": 0,
            "next_attempt": 0,
            "running_since": None,
            "attempts": deque(),
        })

    def _prune_invalid_desired(self, desired, fields):
        valid = set()
        invalid = set()
        for field_id, url_index in desired:
            field = fields.get(str(field_id))
            destinations = field.get("restream_urls", []) if isinstance(field, dict) else []
            if 0 <= url_index < len(destinations):
                valid.add((field_id, url_index))
            else:
                invalid.add((field_id, url_index))
        if invalid:
            self.desired.update(invalid, False)
            for field_id, url_index in sorted(invalid):
                print(
                    "Restream recovery discarded stale target: "
                    f"field={field_id} destination={url_index}",
                    flush=True,
                )
        return valid

    def monitor_once(self, now=None):
        with self.lock:
            now = self.clock() if now is None else now
            fields = self.fields()
            desired = self._prune_invalid_desired(self.desired.load(), fields)
            for pair in list(self.recovery):
                if pair not in desired:
                    self.recovery.pop(pair, None)

            for field_id, url_index in sorted(desired):
                pair = (field_id, url_index)
                record = self._recovery_record(pair)
                if self.process(field_id, url_index) is not None:
                    if record["running_since"] is None:
                        record["running_since"] = now
                    elif now - record["running_since"] >= HEALTHY_RESET_SECONDS:
                        record["failure_count"] = 0
                        record["next_attempt"] = 0
                        record["attempts"].clear()
                    continue

                record["running_since"] = None
                if now < record["next_attempt"]:
                    continue
                if not self.source_ready(field_id):
                    record["next_attempt"] = now + SOURCE_RETRY_DELAY
                    continue

                attempts = record["attempts"]
                while attempts and now - attempts[0] >= ATTEMPT_WINDOW_SECONDS:
                    attempts.popleft()
                if len(attempts) >= MAX_ATTEMPTS_PER_WINDOW:
                    record["next_attempt"] = now + CIRCUIT_COOLDOWN_SECONDS
                    print(
                        "Restream recovery cooling down: "
                        f"field={field_id} destination={url_index}",
                        flush=True,
                    )
                    continue

                attempts.append(now)
                record["failure_count"] += 1
                delay = RETRY_DELAYS[min(
                    record["failure_count"] - 1,
                    len(RETRY_DELAYS) - 1,
                )]
                record["next_attempt"] = now + delay
                try:
                    result = self._start_selected(
                        field_id,
                        fields[str(field_id)],
                        [url_index],
                    )
                except Exception as error:
                    print(
                        "Restream recovery start failed: "
                        f"field={field_id} destination={url_index} "
                        f"error={type(error).__name__}",
                        flush=True,
                    )
                    continue
                if result["success"]:
                    print(
                        "Restream recovery started: "
                        f"field={field_id} destination={url_index} "
                        f"attempt={record['failure_count']}",
                        flush=True,
                    )

    def monitor_forever(self, stop_event):
        while not stop_event.is_set():
            try:
                self.monitor_once()
            except Exception as error:
                print(
                    "Restream recovery check failed: "
                    f"error={type(error).__name__}",
                    flush=True,
                )
            stop_event.wait(MONITOR_INTERVAL)

    def handle(self, request):
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        action = request.get("action")
        field_id = request.get("field_id")
        url_index = request.get("url_index")
        if action not in {"start", "stop", "restart", "delete_destination"}:
            raise ValueError("unsupported action")
        if type(field_id) is not int or not 1 <= field_id <= 16:
            raise ValueError("invalid field ID")
        if url_index is not None and (type(url_index) is not int or url_index < 0):
            raise ValueError("invalid destination index")
        if action == "delete_destination" and url_index is None:
            raise ValueError("destination index is required")
        return getattr(self, action)(field_id, url_index)


SUPERVISOR = RestreamSupervisor()


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(MAX_REQUEST_SIZE + 1)
        if len(raw) > MAX_REQUEST_SIZE or not raw.endswith(b"\n"):
            response = {"success": False, "message": "invalid request"}
        else:
            try:
                request = json.loads(raw.decode("utf-8"))
                response = SUPERVISOR.handle(request)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                response = {"success": False, "message": str(error)}
            except Exception:
                response = {"success": False, "message": "supervisor error"}
        self.wfile.write((json.dumps(response, separators=(",", ":")) + "\n").encode("utf-8"))


class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    SETTINGS.ensure_runtime_directories()
    socket_path = SETTINGS.supervisor_socket
    if socket_path.exists():
        socket_path.unlink()
    server = UnixServer(str(socket_path), RequestHandler)
    socket_path.chmod(0o600)
    stop_event = threading.Event()
    monitor = threading.Thread(
        target=SUPERVISOR.monitor_forever,
        args=(stop_event,),
        name="restream-recovery",
        daemon=True,
    )
    monitor.start()

    def stop_server(signum, frame):
        stop_event.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        stop_event.set()
        monitor.join(timeout=MONITOR_INTERVAL + 1)
        server.server_close()
        if socket_path.exists():
            socket_path.unlink()


if __name__ == "__main__":
    main()
