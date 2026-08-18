# Role-based access control

Arena RBAC is opt-in so an update cannot lock out an existing node.

## Roles

| Role | Monitoring | Start/stop | Destinations | Fields and publish keys |
|---|---:|---:|---:|---:|
| viewer | yes | no | no | no |
| operator | yes | yes | no | no |
| manager | yes | yes | yes | no |
| admin | yes | yes | yes | yes |

## Create the first administrator

Run the command as the service account so the resulting file remains private
and writable by the manager service:

```bash
cd /opt/arena-rtmp-node
sudo -u arena-rtmp \
    ./.venv/bin/python scripts/manage_users.py \
    set admin --role admin
```

The password is prompted twice and never appears in shell history. Passwords must contain at least 8 characters, including uppercase and lowercase letters and at least one non-whitespace special character. Stored credentials use Werkzeug password
hashes; plaintext passwords are never written.

List safe account metadata:

```bash
sudo -u arena-rtmp \
    /opt/arena-rtmp-node/.venv/bin/python \
    /opt/arena-rtmp-node/scripts/manage_users.py list
```

Disable an account immediately:

```bash
sudo -u arena-rtmp \
    /opt/arena-rtmp-node/.venv/bin/python \
    /opt/arena-rtmp-node/scripts/manage_users.py disable USERNAME
```

## Enable RBAC

Generate a random session secret without printing it into a command line or
checking it into Git. Store it in the protected `config/node.env` file, set
`ARENA_RTMP_RBAC_ENABLED=true`, restart the manager, and verify login before
removing the outer Nginx Basic Auth layer.

Do not enable RBAC before at least one enabled administrator exists.
