# Operations and diagnostics

## Normal service state

```bash
systemctl is-active \
  nginx \
  mediamtx \
  arena-mediamtx-ingress \
  arena-rtmp-auth \
  arena-restream-manager \
  arena-restream-supervisor

systemctl is-enabled \
  nginx \
  mediamtx \
  arena-mediamtx-ingress \
  arena-rtmp-auth \
  arena-restream-manager \
  arena-restream-supervisor
```

Expected RTMP ownership:

```text
MediaMTX compatibility ingress: TCP 1935
Main MediaMTX:                 TCP 19350
```

Nginx remains active for HTTPS and HLS but must not own either RTMP port.

## Safe health endpoints

```bash
curl --silent http://127.0.0.1:5000/api/node/health \
  | python3 -m json.tool

curl --silent http://127.0.0.1:5000/api/node/metrics \
  | python3 -m json.tool
```

In full MediaMTX mode, health requires the MediaMTX API and does not require the
legacy nginx-rtmp XML statistics endpoint.

The public-safe metrics response includes stream counts, HLS state, codecs,
resolution, bitrate estimates, error counters, restream counts and system
resources. It must not expose publish keys, destination URLs, internal
credentials or client addresses.

## MediaMTX paths

The main API is loopback-only:

```bash
curl --silent http://127.0.0.1:9997/v3/paths/list
```

Use local parsing to display only safe fields such as path name, ready state,
source type and inbound frame errors. Do not print complete source objects or
query strings.

## Journals

```bash
journalctl -u mediamtx -f
journalctl -u arena-mediamtx-ingress -f
journalctl -u arena-rtmp-auth -f
journalctl -u arena-restream-supervisor -f
```

Authentication logs record safe place and stream labels plus the result. They
must never record the query string or key.

## Routine changes

- Change per-place camera keys through the Arena application, not by editing
  MediaMTX files.
- Change outgoing destinations through the manager so schema validation,
  audit logging and supervisor coordination remain active.
- Treat changes to `mediamtx.yml`, `ingress.yml`, Nginx routing or systemd
  units as maintenance operations requiring a backup and rollback.
- A normal application update must not restart either MediaMTX process.

## Reboot validation

After a planned reboot:

1. verify all six services are active and enabled;
2. verify port ownership;
3. verify health and safe metrics;
4. verify all expected paths and HLS playlists;
5. verify configured outgoing restreams;
6. inspect restart counters and recent critical journal messages.

## Backups

Back up private configuration with root-only permissions. Required recovery
material includes Arena state, user data, audit data, private environment,
private Nginx profile, both MediaMTX configurations and installed systemd/Nginx
files. HLS segments, PID files and generated previews are runtime data and do
not normally require backup.

Never copy private backup contents into GitHub, chat messages or public support
logs.
