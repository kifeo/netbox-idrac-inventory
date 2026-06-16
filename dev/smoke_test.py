"""
End-to-end smoke test, run inside the netbox container:
  docker compose exec netbox /opt/netbox/venv/bin/python \
      /opt/netbox/netbox/manage.py shell < dev/smoke_test.py

Creates the minimum NetBox objects, a DellServer pointing at the lab iDRAC,
runs the sync synchronously, and prints the result + imported components.
"""
from dcim.models import (
    Device, DeviceRole, DeviceType, Manufacturer, Site,
)
from netbox_idrac_inventory.models import DellServer, DellComponent
from netbox_idrac_inventory.idrac.sync import sync_server

IDRAC_ADDR = "idrac01.example.com"

site, _ = Site.objects.get_or_create(name="Lab", slug="lab")
mfr, _ = Manufacturer.objects.get_or_create(name="Dell", slug="dell")
dtype, _ = DeviceType.objects.get_or_create(
    manufacturer=mfr, model="PowerEdge R450", slug="poweredge-r450",
)
role, _ = DeviceRole.objects.get_or_create(
    name="Server", slug="server", defaults={"color": "00bcd4"},
)
device, _ = Device.objects.get_or_create(
    name="r450-lab-01", site=site, device_type=dtype, role=role,
)

server, created = DellServer.objects.get_or_create(
    device=device, defaults={"idrac_address": IDRAC_ADDR},
)
if not created:
    server.idrac_address = IDRAC_ADDR
    server.save()

print(f"DellServer {'created' if created else 'reused'}: {server}")
print("Running sync_server() ...")
result = sync_server(server)
server.refresh_from_db()

print("\n=== RESULT ===")
print(result)
print("\n=== DellServer ===")
print(f"status={server.sync_status} service_tag={server.service_tag} "
      f"model={server.model} bios={server.bios_version} "
      f"idrac_fw={server.idrac_firmware} last_synced={server.last_synced}")
print(f"device.serial={server.device.serial!r}")

print("\n=== Components by type ===")
from collections import Counter
counts = Counter(
    DellComponent.objects.filter(server=server)
    .values_list("component_type", flat=True)
)
for ctype, n in sorted(counts.items()):
    print(f"  {ctype}: {n}")
print(f"  TOTAL: {DellComponent.objects.filter(server=server).count()}")

print("\n=== Sample rows ===")
for c in DellComponent.objects.filter(server=server).order_by(
        "component_type", "name")[:12]:
    cap = f"{c.capacity_bytes/1e9:.0f}GB" if c.capacity_bytes else "-"
    print(f"  [{c.component_type}] {c.name} | {c.manufacturer} {c.model} "
          f"| sn={c.serial or '-'} | {cap}")
