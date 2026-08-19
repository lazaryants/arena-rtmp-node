# Audit log

Arena RTMP Node records authentication and supported state-changing web actions
in a bounded JSON-lines file. The default path is
`state/audit.jsonl`; it can be overridden with
`ARENA_RTMP_AUDIT_FILE`.

Only administrators can open `/admin/audit/` or read `/api/audit`.

## Recorded metadata

Each record contains:

- UTC timestamp;
- authenticated username and role;
- stable action name;
- success or failure;
- safe identifiers such as field, destination index, or username;
- HTTP method, status, and names of changed fields.

RTMP and RTMPS URLs, publish keys, session and CSRF tokens, passwords, password
hashes, and secret values are never intentionally written. The logger also
removes sensitive mapping keys and redacts RTMP URLs defensively.

## Rotation and permissions

The current file is limited to 5 MiB and keeps three rotated files. Files use
mode `0600` inside the manager service's existing writable state directory.
Audit write failures are reported to the service journal but never interrupt
stream control.

## Action names

Actions include session login/logout, restream start/stop/restart, destination
create/update/delete, field create/update/delete, publish-key rotation, and
user create/role/access/password changes.
