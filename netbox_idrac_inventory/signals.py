"""
Signal handlers for the netbox_idrac_inventory plugin.

Creates custom fields on core NetBox models after migrations run:
  - dcim.Interface: the LLDP neighbour discovered on each Dell network port
      - lldp_remote_chassis: the remote switch identifier (SwitchConnectionID)
      - lldp_remote_port:    the remote switch port (SwitchPortConnectionID)
  - dcim.ModuleBay: the NUMA node a network adapter's PCIe lanes are wired
    to, derived from Dell's Oem.Dell.CPUAffinity (Dell's 1-indexed CPU
    socket, converted to a 0-indexed NUMA node)
      - numa_node: comma-joined node number(s), e.g. "0" or "1"
"""

LLDP_CUSTOM_FIELDS = (
    ("lldp_remote_chassis", "LLDP remote chassis"),
    ("lldp_remote_port", "LLDP remote port"),
)

MODULE_BAY_CUSTOM_FIELDS = (
    ("numa_node", "NUMA node"),
)


def create_lldp_custom_fields(sender, **kwargs):
    """post_migrate handler: ensure the LLDP custom fields exist (idempotent)."""
    from core.models import ObjectType
    from extras.choices import CustomFieldTypeChoices
    from extras.models import CustomField

    try:
        iface_ot = ObjectType.objects.get(app_label="dcim", model="interface")
    except Exception:
        # Interface object type not ready yet (very early migrate); skip — the
        # next post_migrate run will create the fields.
        return

    for name, label in LLDP_CUSTOM_FIELDS:
        cf, _ = CustomField.objects.get_or_create(
            name=name,
            defaults={
                "label": label,
                "type": CustomFieldTypeChoices.TYPE_TEXT,
                "group_name": "LLDP",
                "description": "Discovered from Dell iDRAC (Redfish).",
            },
        )
        cf.object_types.add(iface_ot)


def create_module_bay_custom_fields(sender, **kwargs):
    """post_migrate handler: ensure the ModuleBay custom fields exist (idempotent)."""
    from core.models import ObjectType
    from extras.choices import CustomFieldTypeChoices
    from extras.models import CustomField

    try:
        bay_ot = ObjectType.objects.get(app_label="dcim", model="modulebay")
    except Exception:
        # ModuleBay object type not ready yet (very early migrate); skip —
        # the next post_migrate run will create the fields.
        return

    for name, label in MODULE_BAY_CUSTOM_FIELDS:
        cf, _ = CustomField.objects.get_or_create(
            name=name,
            defaults={
                "label": label,
                "type": CustomFieldTypeChoices.TYPE_TEXT,
                "group_name": "Dell iDRAC",
                "description": "Discovered from Dell iDRAC (Redfish).",
            },
        )
        cf.object_types.add(bay_ot)
