# Full MediaMTX deployment

This document describes the production architecture deployed on the German
Arena76 node. Commands use the default installation paths; adapt only private
profiles and host-specific values.

## Target architecture

Two MediaMTX processes separate public compatibility from canonical media
processing:

1. `arena-mediamtx-ingress.service` listens on public TCP 1935.
2. It accepts only exact `placeN/streamN` paths.
3. MediaMTX sends publish metadata to the Arena auth callback.
4. The callback verifies the configured stream name and per-place key.
5. The ingress forwards accepted media to `placeN` on the main MediaMTX
   process at TCP 19350.
6. The main process provides HLS and input metrics and is the source for
   outgoing restreams.
7. Nginx proxies the old public HLS URL to MediaMTX.

This preserves existing camera URLs while removing Nginx-RTMP from media
ingress.

## Prerequisites

- Linux with systemd;
- Nginx for TLS and HTTP;
- MediaMTX binary at `/usr/local/bin/mediamtx`;
- FFmpeg;
- Python 3.12 or newer;
- service users `arena-rtmp` and `mediamtx`;
- valid TLS certificate;
- protected Arena state containing all per-place publish keys.

Run the repository checks before touching production:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/audit_systemd.py --max-exposure 3.0
sudo ./scripts/update.sh check
```

## 1. Prepare the application

Install or update the managed application under
`/opt/arena-rtmp-node`. Configure the full MediaMTX place set in the private
`node.env`:

```dotenv
ARENA_RTMP_LOCAL_RTMP_ORIGIN=rtmp://127.0.0.1:19350
ARENA_RTMP_MEDIAMTX_API_URL=http://127.0.0.1:9997
ARENA_RTMP_MEDIAMTX_HLS_PLACES=1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16
```

Do not print the rest of `node.env`.

## 2. Prepare the main MediaMTX source

Create a protected working copy:

```bash
install -d -m 700 /root/arena-mediamtx-private
install -m 600 \
  mediamtx/mediamtx.yml.example \
  /root/arena-mediamtx-private/source.yml
```

Replace `CHANGE_ME_STRONG_MEDIA_PASSWORD` without putting the password in
shell history or terminal output. This account is for trusted direct publishers
such as the local Arena server.

## 3. Generate the compatibility pair

```bash
stage="$(mktemp -d /root/arena-mediamtx-render.XXXXXX)"
chmod 700 "${stage}"

python3 scripts/render_mediamtx_compat.py \
  --main-config /root/arena-mediamtx-private/source.yml \
  --output-dir "${stage}"
```

The renderer adds a dedicated localhost-only publisher to the main candidate,
stores only its SHA-256 value there, and writes the matching plaintext password
only to the protected ingress candidate. It refuses to overwrite existing
output files.

Expected output:

```text
MediaMTX candidates rendered
Main credential storage: SHA-256
Ingress credential storage: protected plaintext
Compatibility paths: 16
Credentials were not displayed
```

Both files must have mode `600`.

## 4. Render Nginx for full MediaMTX mode

The private render profile must contain:

```json
"rtmp_enabled": false,
"mediamtx_hls_upstream": "127.0.0.1:8888",
"mediamtx_hls_places": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
```

Render into staging:

```bash
python3 scripts/render_nginx.py \
  --profile /opt/arena-rtmp-node/config/nginx-render.json \
  --output-dir /root/arena-nginx-stage
```

The generated `arena-rtmp.conf` must contain no `rtmp {` block or
`application place` directive. The HTTP file must contain 16 MediaMTX HLS
locations.

## 5. Back up the live node

Create a root-only backup of at least:

- both `/etc/mediamtx/*.yml` files;
- the installed MediaMTX unit files;
- Nginx RTMP and HTTP fragments;
- private `node.env` and Nginx render profile;
- current service enabled/active states;
- current port owners;
- the Arena state file.

Never print backup contents.

## 6. Controlled activation order

Use a maintenance window and an independent rollback script.

1. Stop the restream supervisor.
2. Install the new main `mediamtx.yml` as `root:mediamtx`, mode `640`.
3. Restart the main MediaMTX and verify TCP 19350 and API 9997.
4. Wait for trusted direct publishers to restore canonical paths.
5. Install `ingress.yml` as `root:mediamtx`, mode `640`.
6. Install and enable `arena-mediamtx-ingress.service`.
7. Install the rendered Nginx files and run `nginx -t`.
8. Restart Nginx so it releases TCP 1935.
9. Start the compatibility ingress and confirm MediaMTX owns TCP 1935.
10. Restart the manager and start the restream supervisor.
11. Verify authentication, all expected paths, HLS and health.

Do not treat an intentionally idle place as a migration failure. Required
production paths, both MediaMTX services, authentication and HLS determine
success.

## 7. Acceptance checks

- TCP 1935 belongs to the compatibility MediaMTX process;
- TCP 19350 belongs to the main MediaMTX process;
- nginx does not own an RTMP port;
- all required systemd units are active and enabled;
- wrong publish key returns HTTP 403 from `/mediamtx-auth`;
- each expected canonical `placeN` is ready with zero inbound frame errors;
- each ready public HLS URL returns a valid `#EXTM3U` playlist;
- `/api/node/health` reports `status=ok`;
- `/api/node/metrics` reports MediaMTX reachable;
- configured outgoing restreams are running;
- recent journals contain no panic, fatal error, traceback, permission denial or
  address conflict.

## Rollback

If a required check fails:

1. stop and disable the compatibility ingress;
2. restore the former main MediaMTX configuration;
3. restore the former Nginx RTMP and HTTP files;
4. restore the former private profile and `node.env`;
5. reload systemd;
6. validate Nginx;
7. restart Nginx, main MediaMTX, auth, manager and supervisor;
8. verify the former port ownership and source paths.

Retain the migration backup until the node has survived a reboot and a useful
period of normal operation.
