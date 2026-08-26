# MediaMTX gateway

Production uses two MediaMTX processes while preserving every existing public
camera URL.

## Processes and ports

| Component | Listener | Purpose |
|---|---:|---|
| `arena-mediamtx-ingress.service` | TCP 1935 | Compatibility ingress for `placeN/streamN?key=...` |
| `mediamtx.service` | TCP 19350 | Canonical RTMP gateway |
| `mediamtx.service` | UDP 8890 | Canonical SRT gateway |
| main MediaMTX HLS | 127.0.0.1:8888 | HLS consumed by Nginx |
| main MediaMTX API | 127.0.0.1:9997 | Health and stream metrics |
| main MediaMTX metrics | 127.0.0.1:9998 | Prometheus-compatible metrics |
| compatibility API | 127.0.0.1:19996 | Local diagnostics only |

The public compatibility process accepts the legacy path
`placeN/streamN`. It sends the original query string to
`http://127.0.0.1:8080/mediamtx-auth`. The Arena auth service validates the
existing per-place key and stream name. An accepted stream is forwarded to the
canonical `placeN` path on the main MediaMTX instance.

The internal forwarding account is restricted to localhost and to
`place1` through `place16`. Its password is stored as SHA-256 in the main
configuration and as protected plaintext in the compatibility configuration.

## Private configuration generation

The repository never contains live credentials. Prepare a private main
configuration first and replace `CHANGE_ME_STRONG_MEDIA_PASSWORD` with the
publisher password used by trusted direct RTMP/SRT senders.

Then render the compatibility pair into a protected staging directory:

```bash
install -d -m 700 /root/arena-mediamtx-private
install -m 600 \
  mediamtx/mediamtx.yml.example \
  /root/arena-mediamtx-private/source.yml

# Edit source.yml without printing its password.
editor /root/arena-mediamtx-private/source.yml

stage="$(mktemp -d /root/arena-mediamtx-render.XXXXXX)"
chmod 700 "${stage}"

python3 scripts/render_mediamtx_compat.py \
  --main-config /root/arena-mediamtx-private/source.yml \
  --output-dir "${stage}"
```

The renderer creates:

- `mediamtx.yml`: main configuration with the hashed localhost-only account;
- `ingress.yml`: compatibility configuration containing the matching internal
  password;
- mode `600` for both files and mode `700` for the output directory;
- no credential output on stdout or stderr.

Never commit either rendered file.

## Lifecycle policy

The normal project updater installs the packaged unit definitions, but it does
not copy `/etc/mediamtx/*.yml` and does not stop, start or restart either
MediaMTX process. Media configuration changes require an explicit maintenance
operation with an independent backup and rollback.

See [MediaMTX deployment](../docs/MEDIAMTX_DEPLOYMENT.md) and
[operations](../docs/OPERATIONS.md).
