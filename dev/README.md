# Dev environment (netbox-docker)

Self-contained NetBox stack for testing the `netbox-idrac-inventory` plugin
against a real iDRAC. Builds the official `netboxcommunity/netbox` image with
the plugin installed, plus an RQ worker (runs the sync job), Postgres, Redis.

## Prerequisites
- Docker + Docker Compose v2
- Network access from the Docker host to the Dell server's iDRAC

## 1. Configure iDRAC credentials

```bash
cd dev
cp .env.example .env
$EDITOR .env        # set IDRAC_USERNAME / IDRAC_PASSWORD
```

## 2. Start the stack

```bash
docker compose up --build      # add -d to detach
```

First boot runs migrations and creates the superuser. Wait until the `netbox`
service is healthy, then open: http://localhost:8000 — login **admin / admin**.

> The plugin ships its migration (`migrations/0001_initial.py`), which NetBox
> applies on first start. The LLDP custom fields are created by a `post_migrate`
> hook (no migration). Only if you change `models.py` do you regenerate:
> `docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py makemigrations netbox_idrac_inventory`
> — the file appears straight in `netbox_idrac_inventory/migrations/` (the
> package is bind-mounted), no copy needed.

## 3. Test against the Dell server

1. UI: **Plugins → iDRAC Inventory → Dell Servers → Add**. Pick a Device,
   enter the iDRAC address (and a per-device username if it differs from the
   default). Save.
2. Open the Dell server (or its Device page) and click **Sync from iDRAC**.
3. Watch the worker: `docker compose logs -f netbox-worker`. The job result
   and any error land in the Dell server's `sync_status` / `sync_message`.

REST equivalent:
```bash
curl -X POST http://localhost:8000/api/plugins/idrac-inventory/servers/1/sync/ \
  -H "Authorization: Token 0123456789abcdef0123456789abcdef01234567"
```

## Useful commands

```bash
docker compose logs -f netbox netbox-worker   # follow logs
docker compose restart netbox netbox-worker   # apply code edits (live-mounted)
docker compose exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_idrac_inventory
docker compose down            # stop
docker compose down -v         # stop + wipe DB/redis volumes
```

Code under `netbox_idrac_inventory/` is bind-mounted, so a `restart` is enough
for `.py` edits. Changes to dependencies or `pyproject.toml` need a rebuild:
`docker compose up --build`.

## Notes
- Credentials, secret key, and API token here are **dev-only**.
- If your iDRAC requires reaching it by hostname, ensure the Docker host can
  resolve/route to it (the containers use the host network stack for egress).
