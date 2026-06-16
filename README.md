# NetBox iDRAC Inventory Plugin

A [NetBox](https://netbox.dev) plugin that synchronizes Dell PowerEdge server
hardware inventory into NetBox by querying each server's iDRAC management
interface via the Redfish API.

---

## Features

- **One-to-one Dell server record** linked to a NetBox Device. Adding a Dell
  server creates the Device for you (its name defaults to the host part of the
  iDRAC FQDN); the record stores the iDRAC address, service tag, BIOS version
  and iDRAC firmware. The device type is set from the iDRAC-reported model on
  the first sync.
- **Hardware component inventory** — CPUs, DIMMs, disks, storage controllers
  and power supplies are discovered and stored as `DellComponent` objects.
- **Health status** — the iDRAC `Status.Health` of the server (rolled up) and
  of each component is mapped to a colored `health` badge (OK / Warning /
  Critical), so a failed PSU or disk is visible at a glance and filterable.
- **iDRAC management IP** — the iDRAC's own NIC is modelled as a mgmt-only
  `iDRAC` interface (with its MAC), the iDRAC IPv4 is created in IPAM and set
  as the device's **out-of-band IP** (`oob_ip`).
- **Native network modelling** — each physical network adapter is created as a
  NetBox `Module` (with a matching `ModuleType`) installed in a `ModuleBay` on
  the device, and each physical port becomes an `Interface` with its MAC
  address and link speed.
- **LLDP discovery** — the LLDP neighbour reported by iDRAC for each connected
  port (remote switch + remote port) is stored in the `lldp_remote_chassis`
  and `lldp_remote_port` custom fields on the interface. These custom fields
  are created automatically on first migrate.
- **Sync-on-demand** — trigger a sync from the NetBox UI or via the REST API
  (`POST .../servers/<id>/sync/`); sync runs as a background job.
- **Scheduled sync** — set `sync_interval_minutes` > 0 to register a recurring
  system job that re-syncs every Dell server automatically.
- **Network discovery** — define a **Scan Range** (CIDR / range / hosts); a
  discovery job probes each iDRAC and imports it, attaching to an existing
  device with the same service tag when one exists (no duplicate) or creating
  a new one.
- **Full REST API** at `/api/plugins/idrac-inventory/` (servers + components).
- **GraphQL** queries `dell_server` / `dell_server_list` /
  `dell_component` / `dell_component_list` exposed through NetBox's Strawberry
  schema.
- **Credentials** — a global iDRAC password comes from `PLUGINS_CONFIG` /
  environment; an optional **per-device password** (when machines differ) is
  stored **encrypted at rest** (Fernet, keyed on NetBox `SECRET_KEY`) and is
  never returned by the API.

---

## Compatibility

| Plugin version | NetBox version |
|----------------|---------------|
| 0.1.x          | 4.1 or later  |

Requires Python 3.10+.

---

## Installation

### 1. Install the package

```bash
pip install netbox-idrac-inventory
```

### 2. Add to `configuration.py`

```python
PLUGINS = [
    "netbox_idrac_inventory",
]

PLUGINS_CONFIG = {
    "netbox_idrac_inventory": {
        # iDRAC credentials used when a DellServer has no per-device username set.
        "idrac_default_username": "root",
        # Prefer setting the password via an environment variable rather than
        # committing it to the config file.  The plugin checks the env var
        # IDRAC_DEFAULT_PASSWORD before falling back to this value.
        "idrac_default_password": "",
        # Set to True (and provide a valid CA bundle) in production.
        "idrac_verify_ssl": False,
        # HTTP request timeout in seconds for iDRAC Redfish calls.
        "idrac_timeout": 30,
        # When True, the sync writes the iDRAC service tag to Device.serial
        # in NetBox so the physical device record stays up to date.
        "update_device_serial": True,
        # When True, the sync creates a mgmt-only "iDRAC" interface with the
        # iDRAC IP and sets it as the device's out-of-band IP.
        "manage_idrac_interface": True,
        # Minutes between automatic syncs of every Dell server (0 = disabled,
        # sync stays manual). Read at worker startup — restart the RQ worker
        # after changing it.
        "sync_interval_minutes": 0,
    }
}
```

### 3. Apply database migrations

```bash
python manage.py migrate
```

---

## Usage

### Add a Dell server

Two ways:

- **From scratch** — go to **Plugins → iDRAC Inventory → Dell Servers → Add**.
  Enter the iDRAC address, a device **name** (left blank, it defaults to the
  host part of the iDRAC FQDN, e.g. `host01.ipmi.example.com` → `host01`), a
  **site** and a **role**. The plugin creates the Device (with a placeholder
  device type, replaced by the real model on the first sync) and links it.
- **From an existing device** — on a Device page, use the **iDRAC Inventory**
  panel's *Add* button; the new record is attached to that device instead of
  creating a new one.

Optionally set a per-device iDRAC username; otherwise the plugin default is
used.

### Trigger a sync

- **UI**: open the DellServer (or its Device) page and click **Sync from
  iDRAC**. The sync runs as a NetBox background job; refresh to see the result
  in `sync_status` / `sync_message`.
- **REST API**:

  ```bash
  curl -X POST \
    -H "Authorization: Token <your-token>" \
    https://netbox.example.com/api/plugins/idrac-inventory/servers/42/sync/
  ```

  Returns `HTTP 202` with the background job ID:

  ```json
  {
    "job_id": 123,
    "job_url": "https://netbox.example.com/api/extras/jobs/123/",
    "message": "Sync job enqueued for my-server-01 (SVC00042)."
  }
  ```

### Discover servers from a range

Under **Plugins → iDRAC Inventory → Scan Ranges → Add**, define one or more
targets (one per line or comma-separated): a CIDR (`10.0.0.0/24`), a range
(`10.0.0.10-20`) or single hosts, plus the site and role for created devices.
Click **Run scan** (or `POST .../scan-ranges/<id>/run/`). For each reachable
iDRAC the discovery attaches to an existing device with the same service tag,
or creates one, then syncs it.

### REST API overview

Base path: `/api/plugins/idrac-inventory/`

| Method | Endpoint                          | Description                 |
|--------|-----------------------------------|-----------------------------|
| GET    | `/servers/`                       | List all Dell servers       |
| POST   | `/servers/`                       | Create a Dell server record |
| GET    | `/servers/<id>/`                  | Retrieve a Dell server      |
| PATCH  | `/servers/<id>/`                  | Update a Dell server        |
| DELETE | `/servers/<id>/`                  | Delete a Dell server        |
| POST   | `/servers/<id>/sync/`             | Enqueue an iDRAC sync job   |
| GET    | `/components/`                    | List all components         |
| GET    | `/components/<id>/`               | Retrieve a component        |
| GET/POST | `/scan-ranges/`                 | List / create scan ranges   |
| POST   | `/scan-ranges/<id>/run/`          | Enqueue a discovery job     |

Full OpenAPI schema is available at `/api/schema/` in your NetBox instance.

### GraphQL

```graphql
query {
  dell_server_list {
    id
    service_tag
    model
    sync_status
    device { name }
  }
}

query {
  dell_server(id: 42) {
    bios_version
    idrac_firmware
    last_synced
  }
}
```

---

## Credentials and security

- At sync time the plugin resolves the password in this order:
  1. The **per-device** `idrac_password` (or a scan range's), when set.
  2. Environment variable `IDRAC_DEFAULT_PASSWORD` (recommended default for
     production — set it in your process manager / secrets manager).
  3. `PLUGINS_CONFIG["netbox_idrac_inventory"]["idrac_default_password"]`.
- **Per-device password** — when servers don't share one password, set it on
  the DellServer (or scan range). It is **encrypted at rest** with a key
  derived from NetBox's `SECRET_KEY` (Fernet), is write-only in the form, and
  is never returned by the REST or GraphQL API. Rotating `SECRET_KEY`
  invalidates stored passwords (re-enter them). If you only have one shared
  password, leave these blank and use the global default above.
- The per-device `idrac_username` overrides `idrac_default_username` likewise.
- In production, set `idrac_verify_ssl: true` and provide a trusted CA bundle
  so TLS certificates are validated.

---

## Development

### Quick start with Docker

A self-contained NetBox stack (NetBox + worker + Postgres + Redis) with the
plugin pre-installed lives under [`dev/`](dev/). See [`dev/README.md`](dev/README.md):

```bash
cd dev
cp .env.example .env      # set IDRAC_USERNAME / IDRAC_PASSWORD
docker compose up --build # NetBox at http://localhost:8000 (admin / admin)
```

### Migrations

The plugin **ships its schema migration** (`migrations/0001_initial.py`), so a
plain `python manage.py migrate` is all that is needed. The LLDP custom fields
on `dcim.Interface` are **not** a migration — they are created idempotently by
a `post_migrate` signal (see `signals.py`) so they stay correct across NetBox
versions. If you change the models, regenerate with
`python manage.py makemigrations netbox_idrac_inventory` and commit the result.

### Running tests

Tests must run inside the NetBox Django environment:

```bash
# From the NetBox source root with the plugin installed:
python manage.py test netbox_idrac_inventory
# or, with the dev stack running:
docker compose exec netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py test netbox_idrac_inventory
```

### Project layout

```
netbox_idrac_inventory/
  api/
    serializers.py     # NetBoxModelSerializer subclasses
    views.py           # NetBoxModelViewSet subclasses + sync action
    urls.py            # NetBoxRouter registration
  graphql/
    types.py           # Strawberry-django type definitions
    schema.py          # Root query class + schema list
  idrac/
    client.py          # IdracClient — Redfish wrapper (sushy), plain dicts
    sync.py            # sync_server() — iDRAC -> NetBox reconcile logic
    discovery.py       # discover_range() — scan a range and import iDRACs
  migrations/
    0001_initial.py    # DellServer / DellComponent schema
  templates/netbox_idrac_inventory/   # detail pages + Device-page panel
  tests/
    test_models.py     # Model unit tests
    test_idrac.py      # Sync engine + network/LLDP tests (fake client)
    test_api.py        # REST API tests (NetBox APIViewTestCases)
    test_forms.py      # Device-creating form + name helper
  __init__.py          # PluginConfig (settings) + post_migrate hook
  choices.py           # SyncStatusChoices, ComponentTypeChoices
  models.py            # DellServer, DellComponent, DellScanRange
  forms.py             # Forms (DellServerForm creates/links the Device)
  tables.py            # DellServerTable, DellComponentTable
  filtersets.py        # DellServerFilterSet, DellComponentFilterSet
  views.py             # CRUD views + DellServerSyncView
  urls.py              # UI URL routes
  navigation.py        # Plugin menu
  template_content.py  # Dell panel on the Device page
  jobs.py              # DellSyncJob + enqueue_sync()
  signals.py           # post_migrate: create LLDP custom fields
  utils.py             # default_device_name(), get_or_create_manufacturer()
```
