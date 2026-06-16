"""Add several lab servers, sync them, and report ModuleType reuse + LLDP."""
from dcim.models import (
    Device, DeviceRole, DeviceType, Manufacturer, Module, ModuleType, Site,
    Interface,
)
from netbox_idrac_inventory.models import DellServer
from netbox_idrac_inventory.idrac.sync import sync_server

SERVERS = [
    ("r450-u30", "idrac01.example.com", "PowerEdge R450"),
    ("r630-u35", "idrac02.example.com", "PowerEdge R630"),
    ("r630-u38", "idrac03.example.com", "PowerEdge R630"),
]

site, _ = Site.objects.get_or_create(name="Lab", slug="lab")
dell, _ = Manufacturer.objects.get_or_create(name="Dell", slug="dell")
role, _ = DeviceRole.objects.get_or_create(
    name="Server", slug="server", defaults={"color": "00bcd4"})

for name, addr, model in SERVERS:
    dtype, _ = DeviceType.objects.get_or_create(
        manufacturer=dell, model=model, slug=model.lower().replace(" ", "-"))
    device, _ = Device.objects.get_or_create(
        name=name, site=site, device_type=dtype, role=role)
    srv, created = DellServer.objects.get_or_create(
        device=device, defaults={"idrac_address": addr})
    if not created:
        srv.idrac_address = addr
        srv.save()
    res = sync_server(srv)
    print(f"{name}: {res['message']}")

print("\n=== ModuleTypes (reused across machines) ===")
for mt in ModuleType.objects.all().order_by("model"):
    n = Module.objects.filter(module_type=mt).count()
    print(f"  [{mt.manufacturer}] {mt.model!r}  PN={mt.part_number!r}  "
          f"-> installed {n}x")

print("\n=== LLDP neighbours discovered ===")
found = False
for i in Interface.objects.exclude(
        custom_field_data__lldp_remote_chassis="").order_by("device__name", "name"):
    cf = i.custom_field_data or {}
    rc, rp = cf.get("lldp_remote_chassis"), cf.get("lldp_remote_port")
    if rc or rp:
        found = True
        print(f"  {i.device.name}/{i.name}: chassis={rc} port={rp}")
if not found:
    print("  (none — links down or switch not sending LLDP)")
