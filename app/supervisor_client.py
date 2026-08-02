"""Small safe client for the local restream supervisor."""

import json
import socket


class SupervisorUnavailable(RuntimeError):
    pass


class SupervisorClient:
    def __init__(self, socket_path, timeout=5):
        self.socket_path = str(socket_path)
        self.timeout = timeout

    def request(self, action, field_id, url_index=None):
        payload = {
            "action": action,
            "field_id": field_id,
        }
        if url_index is not None:
            payload["url_index"] = url_index

        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("supervisor request is too large")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(self.timeout)
                client.connect(self.socket_path)
                client.sendall(encoded)
                response = bytearray()
                while not response.endswith(b"\n"):
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
                    if len(response) > 65536:
                        raise SupervisorUnavailable("supervisor response is too large")
        except (OSError, TimeoutError) as error:
            raise SupervisorUnavailable("restream supervisor is unavailable") from error

        try:
            result = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SupervisorUnavailable("invalid supervisor response") from error
        if not isinstance(result, dict) or type(result.get("success")) is not bool:
            raise SupervisorUnavailable("invalid supervisor response")
        return result
