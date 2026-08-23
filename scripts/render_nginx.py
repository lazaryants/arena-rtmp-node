#!/usr/bin/env python3
"""Render server-specific Nginx files without activating them."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = PROJECT_ROOT / "nginx" / "templates"
HOSTNAME_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
UPSTREAM_RE = re.compile(r"127\.0\.0\.1:[1-9][0-9]{0,4}\Z")
NGINX_PATH_RE = re.compile(r"/[A-Za-z0-9._/-]+\Z")


def absolute_path(value, name):
    if not isinstance(value, str) or not NGINX_PATH_RE.fullmatch(value):
        raise ValueError(f"{name} contains unsafe characters")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{name} must be an absolute path")
    return str(path)


def validate_profile(profile):
    server_names = profile.get("server_names")
    if not isinstance(server_names, list) or not server_names:
        raise ValueError("server_names must be a non-empty list")
    if not all(isinstance(name, str) and HOSTNAME_RE.fullmatch(name) for name in server_names):
        raise ValueError("server_names contains an invalid hostname")

    manager_upstream = profile.get("manager_upstream", "127.0.0.1:5000")
    if not isinstance(manager_upstream, str) or not UPSTREAM_RE.fullmatch(manager_upstream):
        raise ValueError("manager_upstream must use 127.0.0.1 and a valid port")

    auth_callback = profile.get("auth_callback", "http://127.0.0.1:8080/auth")
    try:
        parsed_callback = urlparse(auth_callback)
        callback_port = parsed_callback.port
    except (TypeError, ValueError):
        callback_port = None
    if (
        parsed_callback.scheme != "http"
        or parsed_callback.hostname != "127.0.0.1"
        or parsed_callback.path != "/auth"
        or callback_port is None
        or parsed_callback.username is not None
        or parsed_callback.password is not None
        or parsed_callback.query
        or parsed_callback.fragment
    ):
        raise ValueError("auth_callback must be a local http://127.0.0.1:PORT/auth URL")

    auth_places = profile.get("auth_places", [])
    if (
        not isinstance(auth_places, list)
        or any(type(place) is not int or not 1 <= place <= 16 for place in auth_places)
        or len(set(auth_places)) != len(auth_places)
    ):
        raise ValueError("auth_places must contain unique integers from 1 to 16")

    mediamtx_hls_upstream = profile.get("mediamtx_hls_upstream")
    if (
        mediamtx_hls_upstream is not None
        and (
            not isinstance(mediamtx_hls_upstream, str)
            or not UPSTREAM_RE.fullmatch(mediamtx_hls_upstream)
        )
    ):
        raise ValueError(
            "mediamtx_hls_upstream must use 127.0.0.1 and a valid port"
        )

    mediamtx_hls_places = profile.get("mediamtx_hls_places", [])
    if (
        not isinstance(mediamtx_hls_places, list)
        or any(
            type(place) is not int or not 1 <= place <= 16
            for place in mediamtx_hls_places
        )
        or len(set(mediamtx_hls_places)) != len(mediamtx_hls_places)
    ):
        raise ValueError(
            "mediamtx_hls_places must contain unique integers from 1 to 16"
        )
    if mediamtx_hls_places and mediamtx_hls_upstream is None:
        raise ValueError(
            "mediamtx_hls_upstream is required when MediaMTX HLS places are set"
        )

    rtmp_port = profile.get("rtmp_port", 1935)
    if type(rtmp_port) is not int or not 1 <= rtmp_port <= 65535:
        raise ValueError("rtmp_port must be an integer from 1 to 65535")

    return {
        "server_names": server_names,
        "tls_certificate": absolute_path(profile["tls_certificate"], "tls_certificate"),
        "tls_certificate_key": absolute_path(
            profile["tls_certificate_key"],
            "tls_certificate_key",
        ),
        "web_root": absolute_path(profile["web_root"], "web_root").rstrip("/"),
        "hls_root": absolute_path(profile["hls_root"], "hls_root").rstrip("/"),
        "basic_auth_file": absolute_path(
            profile["basic_auth_file"],
            "basic_auth_file",
        ),
        "manager_upstream": manager_upstream,
        "rtmp_port": rtmp_port,
        "auth_callback": auth_callback,
        "auth_places": set(auth_places),
        "mediamtx_hls_upstream": mediamtx_hls_upstream,
        "mediamtx_hls_places": sorted(mediamtx_hls_places),
    }


def render_applications(profile):
    applications = []
    for place_id in range(1, 17):
        lines = [
            f"        application place{place_id} {{",
            "            live on;",
            "            record off;",
        ]
        if place_id in profile["auth_places"]:
            lines.extend([
                "",
                "            notify_method post;",
                f"            on_publish {profile['auth_callback']};",
            ])
        lines.extend([
            "",
            "            hls on;",
            f"            hls_path {profile['hls_root']}/place{place_id};",
            "            hls_fragment 4;",
            "            hls_playlist_length 16;",
            "            hls_cleanup on;",
            "            hls_type live;",
            "        }",
        ])
        applications.append("\n".join(lines))
    return "\n\n".join(applications)


def render_mediamtx_hls_locations(profile):
    upstream = profile["mediamtx_hls_upstream"]
    blocks = []
    for place_id in profile["mediamtx_hls_places"]:
        blocks.append(
            "\n".join([
                f"    location ^~ /hls/place{place_id}/ {{",
                (
                    f"        rewrite ^/hls/place{place_id}/stream{place_id}"
                    rf"\.m3u8$ /place{place_id}/index.m3u8 break;"
                ),
                (
                    f"        rewrite ^/hls/place{place_id}/(.*)$ "
                    f"/place{place_id}/$1 break;"
                ),
                f"        proxy_pass http://{upstream};",
                "        proxy_http_version 1.1;",
                "        proxy_buffering off;",
                "        proxy_request_buffering off;",
                "        proxy_read_timeout 30s;",
                (
                    f"        proxy_cookie_path /place{place_id}/ "
                    f"/hls/place{place_id}/;"
                ),
                "        add_header Cache-Control no-cache always;",
                "        add_header Access-Control-Allow-Origin * always;",
                "        expires -1;",
                "        auth_basic off;",
                "    }",
            ])
        )
    return "\n\n".join(blocks)


def replace_markers(template, replacements):
    rendered = template
    for marker, value in replacements.items():
        rendered = rendered.replace(f"@@{marker}@@", str(value))
    remaining = re.findall(r"@@[A-Z0-9_]+@@", rendered)
    if remaining:
        raise ValueError(f"unresolved template markers: {remaining}")
    return rendered


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as file:
        temporary_path = Path(file.name)
        file.write(content)
        file.flush()
        os.fsync(file.fileno())
    temporary_path.chmod(0o644)
    temporary_path.replace(path)


def render(profile_path, output_dir):
    profile = validate_profile(json.loads(profile_path.read_text(encoding="utf-8")))

    rtmp_template = (TEMPLATE_ROOT / "rtmp.conf.template").read_text(encoding="utf-8")
    http_template = (TEMPLATE_ROOT / "http-site.conf.template").read_text(encoding="utf-8")
    stat_template = (TEMPLATE_ROOT / "rtmp-stat-local.conf").read_text(encoding="utf-8")

    rtmp = replace_markers(rtmp_template, {
        "RTMP_PORT": profile["rtmp_port"],
        "APPLICATIONS": render_applications(profile),
    })
    http = replace_markers(http_template, {
        "SERVER_NAMES": " ".join(profile["server_names"]),
        "TLS_CERTIFICATE": profile["tls_certificate"],
        "TLS_CERTIFICATE_KEY": profile["tls_certificate_key"],
        "WEB_ROOT": profile["web_root"],
        "HLS_ROOT": profile["hls_root"],
        "BASIC_AUTH_FILE": profile["basic_auth_file"],
        "MANAGER_UPSTREAM": profile["manager_upstream"],
        "MEDIAMTX_HLS_LOCATIONS": render_mediamtx_hls_locations(profile),
    })

    outputs = {
        "arena-rtmp.conf": rtmp,
        "arena-rtmp-http.conf": http,
        "arena-rtmp-stat-local.conf": stat_template,
    }
    for filename, content in outputs.items():
        atomic_write(output_dir / filename, content)
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    outputs = render(args.profile, args.output_dir)
    for filename in outputs:
        print(args.output_dir / filename)


if __name__ == "__main__":
    main()
