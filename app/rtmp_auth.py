#!/usr/bin/env python3
import hmac
import json
import os
import re
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path
from urllib.parse import parse_qs

CONFIG_FILE = Path(os.environ.get(
    "CRICKET_RTMP_CONFIG",
    "/opt/restream-config.json",
))
MAX_BODY_SIZE = 65536
PLACE_RE = re.compile(r"place([1-9]|1[0-6])")


def load_config():
    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if not isinstance(config, dict):
        raise ValueError("Invalid configuration root")

    return config


def safe_label(value):
    return re.sub(
        r"[^A-Za-z0-9_.-]",
        "_",
        str(value),
    )[:64]


def authorize_publish(
    app_name,
    stream_name,
    raw_args,
    provided_key="",
):
    match = PLACE_RE.fullmatch(app_name)

    if not match:
        return 403, "invalid_app"

    place_id = match.group(1)
    config = load_config()
    field = config.get("fields", {}).get(place_id)

    if not isinstance(field, dict):
        return 403, "unknown_place"

    expected_stream = (
        field.get("stream_key")
        or f"stream{place_id}"
    )

    if stream_name != expected_stream:
        return 403, "invalid_stream"

    # Поэтапная миграция:
    # площадки без включённой проверки пока разрешаются.
    if field.get("publish_auth_enabled") is not True:
        return 200, "legacy_allowed"

    expected_key = field.get("key")

    if not isinstance(expected_key, str) or not expected_key:
        return 403, "key_not_configured"

    # Nginx-RTMP обычно передаёт аргументы
    # stream URL отдельными POST-полями.
    # Поле args оставляем как совместимый fallback.
    if not provided_key:
        args = parse_qs(
            raw_args or "",
            keep_blank_values=True,
        )
        provided_key = args.get(
            "key",
            [""],
        )[0]

    if not isinstance(provided_key, str):
        return 403, "invalid_key"

    if not hmac.compare_digest(
        provided_key,
        expected_key,
    ):
        return 403, "invalid_key"

    return 200, "authorized"


class AuthHandler(BaseHTTPRequestHandler):
    server_version = "CricketRTMPAuth/2"

    def send_text(self, status, text):
        payload = (text + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self.send_text(200, "ok")
        else:
            self.send_text(404, "not found")

    def do_POST(self):
        if self.path != "/auth":
            self.send_text(404, "not found")
            return

        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )

            if (
                content_length < 0
                or content_length > MAX_BODY_SIZE
            ):
                self.send_text(413, "request too large")
                return

            body = self.rfile.read(
                content_length
            ).decode(
                "utf-8",
                errors="replace",
            )

            params = parse_qs(
                body,
                keep_blank_values=True,
            )

            app_name = params.get(
                "app",
                [""],
            )[0]
            stream_name = params.get(
                "name",
                [""],
            )[0]
            raw_args = params.get(
                "args",
                [""],
            )[0]
            provided_key = params.get(
                "key",
                [""],
            )[0]

            status, result = authorize_publish(
                app_name,
                stream_name,
                raw_args,
                provided_key,
            )

        except Exception:
            status, result = 503, "auth_error"
            app_name = "unknown"
            stream_name = "unknown"

        print(
            "RTMP auth: "
            f"app={safe_label(app_name)} "
            f"stream={safe_label(stream_name)} "
            f"result={result}",
            flush=True,
        )

        self.send_text(
            status,
            "OK" if status == 200 else "Forbidden",
        )

    def log_message(self, format_string, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", 8080),
        AuthHandler,
    )

    print(
        "RTMP Auth v2 listening on 127.0.0.1:8080",
        flush=True,
    )

    server.serve_forever()
