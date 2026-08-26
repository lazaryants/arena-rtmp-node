#!/usr/bin/env python3
"""Render protected MediaMTX compatibility-ingress candidates."""

import argparse
import base64
import hashlib
import os
import secrets
from pathlib import Path
from urllib.parse import urlencode


USERNAME = "arena-ingress-v1"
PATH_PATTERN = "~^place([1-9]|1[0-6])$"


def private_write(path, content):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
        ) as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def render_main(source, password):
    text = source.read_text(encoding="utf-8")

    if f"  - user: {USERNAME}\n" in text:
        raise ValueError(
            "dedicated ingress user already exists"
        )

    auth_marker = "authInternalUsers:\n"
    if text.count(auth_marker) != 1:
        raise ValueError(
            "unexpected authInternalUsers section"
        )

    auth_start = text.index(auth_marker)
    any_marker = "  - user: any\n"
    any_position = text.find(
        any_marker,
        auth_start,
    )
    if any_position < 0:
        raise ValueError(
            "anonymous internal user marker was not found"
        )

    password_hash = (
        "sha256:"
        + base64.b64encode(
            hashlib.sha256(
                password.encode("utf-8")
            ).digest()
        ).decode("ascii")
    )

    user_block = (
        f"  - user: {USERNAME}\n"
        f"    pass: '{password_hash}'\n"
        '    ips: ["127.0.0.1", "::1"]\n'
        "    permissions:\n"
        "      - action: publish\n"
        f"        path: '{PATH_PATTERN}'\n"
        "\n"
    )

    return (
        text[:any_position]
        + user_block
        + text[any_position:]
    )


def render_ingress(password):
    query = urlencode({
        "user": USERNAME,
        "pass": password,
    })

    lines = [
        "logLevel: info",
        "logDestinations: [stdout]",
        "readTimeout: 15s",
        "writeTimeout: 15s",
        "writeQueueSize: 2048",
        "",
        "authMethod: http",
        (
            "authHTTPAddress: "
            "http://127.0.0.1:8080/mediamtx-auth"
        ),
        "authHTTPExclude:",
        "  - action: read",
        "  - action: playback",
        "  - action: api",
        "  - action: metrics",
        "  - action: pprof",
        "",
        "api: true",
        "apiAddress: 127.0.0.1:19996",
        "metrics: false",
        "pprof: false",
        "playback: false",
        "",
        "rtsp: false",
        "rtmp: true",
        "rtmpAddress: :1935",
        "hls: false",
        "webrtc: false",
        "srt: false",
        "moq: false",
        "",
        "paths:",
    ]

    for number in range(1, 17):
        destination = (
            "rtmp://127.0.0.1:19350"
            f"/place{number}?{query}"
        )
        lines.extend([
            f'  "place{number}/stream{number}":',
            "    forward:",
            f"      - dest: '{destination}'",
        ])

    return "\n".join(lines) + "\n"


def parse_arguments():
    parser = argparse.ArgumentParser(
        description=(
            "Render private MediaMTX main and "
            "compatibility-ingress candidates."
        ),
    )
    parser.add_argument(
        "--main-config",
        required=True,
        type=Path,
        help="existing main MediaMTX source configuration",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="protected staging directory",
    )
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    source = arguments.main_config.resolve()
    output_dir = arguments.output_dir.resolve()

    if not source.is_file():
        raise SystemExit(
            "main configuration does not exist"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )
    output_dir.chmod(0o700)

    main_output = output_dir / "mediamtx.yml"
    ingress_output = output_dir / "ingress.yml"

    if main_output.exists() or ingress_output.exists():
        raise SystemExit(
            "output files already exist"
        )

    password = secrets.token_urlsafe(48)

    try:
        main_text = render_main(source, password)
        ingress_text = render_ingress(password)
        private_write(main_output, main_text)
        private_write(ingress_output, ingress_text)
    except Exception as error:
        main_output.unlink(missing_ok=True)
        ingress_output.unlink(missing_ok=True)
        raise SystemExit(str(error)) from error

    print("MediaMTX candidates rendered")
    print("Main credential storage: SHA-256")
    print("Ingress credential storage: protected plaintext")
    print("Compatibility paths: 16")
    print("Credentials were not displayed")


if __name__ == "__main__":
    main()
