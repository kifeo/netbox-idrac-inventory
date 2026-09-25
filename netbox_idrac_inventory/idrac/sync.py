"""
Mapping and synchronisation engine for Dell iDRAC -> NetBox.

This module is framework-aware (Django ORM, NetBox models) but contains no
view or form logic. It is callable from a background job, a management
command, or unit tests (pass a ``client`` fixture to bypass the real iDRAC).

Password security note
----------------------
The iDRAC password is resolved at sync time: the per-device password
(encrypted at rest) when set, else the ``IDRAC_DEFAULT_PASSWORD``
environment variable, else the plugin config. It is never stored in the
database in plaintext, and a per-device password that can no longer be
decrypted fails the sync instead of silently falling back to the default.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone
from netbox.plugins import get_plugin_config

from netbox_idrac_inventory.choices import (
    ComponentTypeChoices,
    HealthChoices,
    SyncStatusChoices,
)
from netbox_idrac_inventory.idrac.client import IdracClient
from netbox_idrac_inventory.utils import (
    check_address_allowed,
    get_or_create_manufacturer,
)

if TYPE_CHECKING:
    from netbox_idrac_inventory.models import DellServer

log = logging.getLogger(__name__)

PLUGIN_NAME = "netbox_idrac_inventory"

# LLDP custom-field names (created via post_migrate, see signals.py).
CF_LLDP_CHASSIS = "lldp_remote_chassis"
CF_LLDP_PORT = "lldp_remote_port"

# Module bays the plugin creates itself (when the device type has no matching
# bay) are named after the Dell adapter FQDD, which always starts with this
# prefix; used to scope reconciliation/deletion. Ports keep FQDD names too.
_NIC_BAY_PREFIX = "NIC."

# Dell adapter FQDD (NIC.Slot.2, NIC.Integrated.1, NIC.Embedded.1) -> the
# ``position`` of the device-type module bay that houses it. Positions follow
# the netbox-community devicetype-library conventions seen on Dell types:
# PCIe-2, PCIe-Gen3-2, PCIE2, slot-2 / NDC-1, inic-1, OCP-1 / enic-1. Within
# one FQDD kind, earlier patterns win when a type has several candidates.
_FQDD_RE = re.compile(r"^NIC\.(Slot|Integrated|Embedded)\.(\d+)$", re.IGNORECASE)
_BAY_POSITION_PATTERNS = {
    "slot": [re.compile(r"^(?:pcie(?:-gen\d+)?|slot)[-_ ]?(\d+)$", re.IGNORECASE)],
    "integrated": [
        re.compile(r"^inic[-_ ]?(\d+)$", re.IGNORECASE),
        re.compile(r"^ndc[-_ ]?(\d+)$", re.IGNORECASE),
        re.compile(r"^ocp[-_ ]?(\d+)$", re.IGNORECASE),
    ],
    "embedded": [re.compile(r"^enic[-_ ]?(\d+)$", re.IGNORECASE)],
}


def _config(key: str):
    """Read a plugin setting (falls back to PluginConfig.default_settings)."""
    return get_plugin_config(PLUGIN_NAME, key)


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def resolve_credentials(server: DellServer) -> tuple[str, str]:
    """
    Return the ``(username, password)`` to use for *server*.

    Username: ``server.idrac_username`` (per-device override) else the plugin
    default. Password resolution order:

    1. ``server.idrac_password`` (per-device, encrypted at rest) when set.
    2. ``IDRAC_DEFAULT_PASSWORD`` environment variable.
    3. The plugin's ``idrac_default_password`` setting.
    """
    from netbox_idrac_inventory.utils import decrypt_secret

    username = server.idrac_username or _config("idrac_default_username")
    password = (
        decrypt_secret(server.idrac_password)
        or os.environ.get("IDRAC_DEFAULT_PASSWORD")
        or _config("idrac_default_password")
    )
    return username, password


# ---------------------------------------------------------------------------
# Component mapping (CPU / memory / controllers / disks / PSUs)
# ---------------------------------------------------------------------------

# Promoted columns copied straight from each client getter dict.
_COMPONENT_COLUMNS = (
    "name", "manufacturer", "model", "serial", "part_number", "firmware",
)

# (component type, client getter, log label, extra keys kept in `data`).
# NICs are intentionally absent: network adapters are modelled natively as
# dcim.Module + dcim.Interface, see _sync_network_adapters().
_COMPONENT_SPECS = (
    (ComponentTypeChoices.TYPE_CPU, "get_processors", "processors",
     ("total_cores", "total_threads", "max_speed_mhz")),
    (ComponentTypeChoices.TYPE_MEMORY, "get_memory", "memory",
     ("speed_mhz", "memory_device_type")),
    (ComponentTypeChoices.TYPE_CONTROLLER, "get_storage_controllers",
     "storage controllers", ()),
    (ComponentTypeChoices.TYPE_DISK, "get_drives", "drives",
     ("media_type", "protocol")),
    (ComponentTypeChoices.TYPE_PSU, "get_power_supplies", "power supplies",
     ("power_capacity_watts",)),
)


def _safe_call(fn, label: str) -> list:
    """Call *fn()* returning its list result; log and return [] on error."""
    try:
        return fn() or []
    except Exception as exc:
        log.warning("iDRAC getter '%s' failed: %s", label, exc)
        return []


def _build_component_rows(client: IdracClient) -> list[dict]:
    """Flatten every component getter into upsert-ready DellComponent dicts."""
    rows: list[dict] = []
    for ctype, getter, label, data_keys in _COMPONENT_SPECS:
        for item in _safe_call(getattr(client, getter), label):
            row = {col: item.get(col, "") for col in _COMPONENT_COLUMNS}
            row["component_type"] = ctype
            row["capacity_bytes"] = item.get("capacity_bytes")
            row["health"] = HealthChoices.from_redfish(item.get("health"))
            row["data"] = {key: item.get(key) for key in data_keys}
            rows.append(row)

    # UpdateService/FirmwareInventory is authoritative for firmware versions
    # and covers components whose own resource omits one (PSUs, backplanes…).
    # Dell keys the entries by FQDD, which is what component names are.
    firmware = {
        entry["fqdd"]: entry["version"]
        for entry in _safe_call(client.get_firmware_inventory, "firmware inventory")
        if entry.get("fqdd") and entry.get("version")
    }
    if firmware:
        for row in rows:
            version = firmware.get(row["name"])
            if version:
                row["firmware"] = version
    return rows


def _reconcile_components(server, rows: list[dict], _log) -> tuple[int, int, int]:
    """Upsert the desired component rows and delete the ones no longer seen."""
    from django.db.models import Q

    from netbox_idrac_inventory.models import DellComponent

    created = updated = deleted = 0
    desired_keys: set[tuple[str, str]] = set()

    for row in rows:
        name = row["name"]
        if not name:
            _log.warning(
                f"Skipping {row['component_type']} component with empty name."
            )
            continue
        ctype = row["component_type"]
        desired_keys.add((ctype, name))
        _, was_created = DellComponent.objects.update_or_create(
            server=server,
            component_type=ctype,
            name=name,
            defaults={
                "manufacturer": row["manufacturer"],
                "model": row["model"],
                "serial": row["serial"],
                "part_number": row["part_number"],
                "firmware": row["firmware"],
                "capacity_bytes": row["capacity_bytes"],
                "health": row["health"],
                "data": row["data"] or {},
            },
        )
        created += was_created
        updated += not was_created

    # Drop components iDRAC no longer reports. Skip when nothing came back, to
    # avoid wiping data on a transient total failure of the getters.
    if desired_keys:
        keep = Q()
        for ctype, name in desired_keys:
            keep |= Q(component_type=ctype, name=name)
        deleted, _ = (
            DellComponent.objects.filter(server=server).exclude(keep).delete()
        )
    return created, updated, deleted


# ---------------------------------------------------------------------------
# Network adapter -> Module / Interface mapping
# ---------------------------------------------------------------------------


def _set_device_type(device, model: str, _log) -> None:
    """
    Point ``device.device_type`` at the iDRAC-reported *model*, creating the
    shared Dell DeviceType on demand. Replaces the "Unknown" placeholder set
    when the device was created on add.
    """
    from dcim.models import DeviceType
    from django.utils.text import slugify

    dtype, _ = DeviceType.objects.get_or_create(
        manufacturer=get_or_create_manufacturer("Dell"),
        model=model,
        defaults={"slug": slugify(model)[:100]},
    )
    if device.device_type_id != dtype.pk:
        device.device_type = dtype
        device.save(update_fields=["device_type"])
        _log.info(f"Set device '{device}' type to '{model}'.")


def _interface_type_for_speed(speed_mbps):
    """Map a port link speed (Mbps) to an InterfaceTypeChoices value."""
    from dcim.choices import InterfaceTypeChoices as Ift

    return {
        1000: Ift.TYPE_1GE_FIXED,
        10000: Ift.TYPE_10GE_SFP_PLUS,
        25000: Ift.TYPE_25GE_SFP28,
        40000: Ift.TYPE_40GE_QSFP_PLUS,
        50000: Ift.TYPE_50GE_SFP56,
        100000: Ift.TYPE_100GE_QSFP28,
    }.get(speed_mbps or 0, Ift.TYPE_OTHER)


def _interface_carries_data(iface) -> bool:
    """
    True if *iface* holds anything a human would not want silently deleted.

    Used to tell a leftover interface the plugin itself created (empty: no
    cable, no IPs) from one that carries real, manually-entered state.
    """
    return bool(iface.cable_id) or iface.ip_addresses.exists()


def _drop_leftover_interface(iface, _log, reason: str) -> None:
    """Delete an empty plugin-created interface and its dangling MACs."""
    from dcim.models import MACAddress
    from django.contrib.contenttypes.models import ContentType

    _log.warning(
        f"Removing empty duplicate interface '{iface}' on {iface.device}: "
        f"{reason}"
    )
    MACAddress.objects.filter(
        assigned_object_type=ContentType.objects.get_for_model(iface.__class__),
        assigned_object_id=iface.pk,
    ).delete()
    iface.delete()


def _match_interface_by_mac(device, mac: str, iface_ct):
    """Return *device*'s interface already holding *mac*, if any."""
    from dcim.models import MACAddress

    if not mac:
        return None
    for macobj in MACAddress.objects.filter(
        mac_address=mac, assigned_object_type=iface_ct
    ).exclude(assigned_object_id=None):
        candidate = macobj.assigned_object
        if candidate is not None and candidate.device_id == device.pk:
            return candidate
    return None


def _sync_interface(device, module, port: dict, iface_ct, _log) -> bool:
    """
    Upsert a single Interface (type, MAC, LLDP) for one adapter port.

    Matched by MAC address first (when the port reports one), falling back
    to name. This lets a device that already had interfaces before being
    onboarded to the plugin — named however the previous tooling/admin chose
    (e.g. "eth0"), not iDRAC's FQDD scheme — get reconciled onto its real
    Dell port name in place, instead of creating a duplicate interface and
    orphaning the original's cable/IP assignments.

    Returns True when the port was reconciled, False when it was skipped
    because the situation was too ambiguous to resolve safely.
    """
    from dcim.models import Interface

    itype = _interface_type_for_speed(port.get("speed_mbps"))
    name = port["name"]
    mac = (port.get("mac_address") or "").upper()

    iface = _match_interface_by_mac(device, mac, iface_ct)

    if iface is None:
        iface, _created = Interface.objects.get_or_create(
            device=device,
            name=name,
            defaults={"type": itype, "module": module},
        )
    elif iface.name != name:
        # Renaming the MAC-matched interface onto the Dell port name, but
        # another interface already holds that name — the duplicate an
        # earlier (pre-0.3.2) sync created before ports were matched by MAC.
        # (device, name) is unique, so renaming blindly raises IntegrityError
        # and breaks every subsequent sync of this device.
        clash = (
            Interface.objects.filter(device=device, name=name)
            .exclude(pk=iface.pk)
            .first()
        )
        if clash is not None:
            if not _interface_carries_data(clash):
                _drop_leftover_interface(
                    clash, _log,
                    f"'{iface}' holds the same MAC and is the cabled one.",
                )
            elif not _interface_carries_data(iface):
                # The MAC-matched one is the empty leftover instead; keep
                # the interface that actually carries the cable/IPs.
                iface = clash
            else:
                _log.warning(
                    f"Skipping port '{name}' on {device}: both '{iface}' "
                    f"(same MAC) and '{clash}' (same name) carry cables or "
                    "IPs. Merge them by hand, then sync again."
                )
                return False

    changed = False
    if iface.name != name:
        iface.name = name
        changed = True
    if iface.module_id != module.pk:
        iface.module = module
        changed = True
    if iface.type != itype:
        iface.type = itype
        changed = True

    cf = dict(iface.custom_field_data or {})
    for key, value in (
        (CF_LLDP_CHASSIS, port.get("lldp_remote_chassis", "")),
        (CF_LLDP_PORT, port.get("lldp_remote_port", "")),
    ):
        if cf.get(key) != value:
            cf[key] = value
            changed = True
    iface.custom_field_data = cf

    if changed:
        iface.save()

    if mac:
        from dcim.models import MACAddress

        macobj, _ = MACAddress.objects.get_or_create(
            mac_address=mac,
            assigned_object_type=iface_ct,
            assigned_object_id=iface.pk,
        )
        if iface.primary_mac_address_id != macobj.pk:
            iface.primary_mac_address = macobj
            iface.save(update_fields=["primary_mac_address"])

    return True


def _ensure_template_bays(device, _log) -> int:
    """
    Create the device-type module bays missing from *device*.

    NetBox only instantiates a device type's module-bay templates when the
    device is created, so bays added to the type later -- or a device whose
    type was set by the sync after creation -- would otherwise never get
    them. Every slot of the Dell model then exists, empty when iDRAC reports
    nothing in it, so a user can still fill it by hand (e.g. a RAID card).
    Returns the number of bays created.
    """
    from dcim.models import ModuleBay, ModuleBayTemplate

    existing = set(
        ModuleBay.objects.filter(device=device).values_list("name", flat=True)
    )
    created = 0
    templates = ModuleBayTemplate.objects.filter(
        device_type=device.device_type_id
    )
    for template in templates:
        bay = template.instantiate(device=device)
        if bay.name in existing:
            continue
        bay.save()
        existing.add(bay.name)
        created += 1
    if created:
        _log.info(
            f"Created {created} module bay(s) on {device} from device type "
            f"'{device.device_type}'."
        )
    return created


def _template_bay_for_fqdd(device, fqdd: str):
    """
    Return the device's non-plugin module bay that houses the adapter
    *fqdd*, matched on the bay ``position`` (see _BAY_POSITION_PATTERNS), or
    ``None`` when the device type has no such bay or the match is ambiguous.
    """
    from dcim.models import ModuleBay

    match = _FQDD_RE.match(fqdd or "")
    if not match:
        return None
    kind, number = match.group(1).lower(), int(match.group(2))

    bays = list(
        ModuleBay.objects.filter(
            device=device, installed_module__isnull=True
        ).exclude(
            name__startswith=_NIC_BAY_PREFIX
        )
    )
    for pattern in _BAY_POSITION_PATTERNS[kind]:
        candidates = [
            bay
            for bay in bays
            if (m := pattern.match((bay.position or "").strip()))
            and int(m.group(1)) == number
        ]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            return None  # ambiguous: leave it to a plugin-named bay
    return None


def _is_plugin_module(module) -> bool:
    """A module the sync put in place carries FQDD-named ports (NIC.*)."""
    return module.interfaces.filter(name__startswith=_NIC_BAY_PREFIX).exists()


def _module_holds_data(module) -> bool:
    """True when any interface of *module* has a cable or an IP address."""
    from dcim.models import Interface

    return (
        Interface.objects.filter(module=module)
        .filter(cable__isnull=False)
        .exists()
        or any(iface.ip_addresses.exists() for iface in module.interfaces.all())
    )


def _bay_for_adapter(device, fqdd: str, _log):
    """
    Pick the bay for adapter *fqdd*: the device-type bay for that slot when
    the device has one, else a plugin bay named after the FQDD.

    A hand-entered module already sitting in the device-type bay is replaced
    when none of its interfaces carries a cable or an IP; otherwise the bay
    is left alone and the adapter goes to a plugin bay, with a warning.
    """
    from dcim.models import Module, ModuleBay

    # The bay may already hold this adapter from a previous sync.
    current = (
        Module.objects.filter(device=device, module_bay__isnull=False)
        .select_related("module_bay")
        .filter(interfaces__name__startswith=f"{fqdd}-")
        .distinct()
        .first()
    )
    if current and not current.module_bay.name.startswith(_NIC_BAY_PREFIX):
        return current.module_bay

    target = _template_bay_for_fqdd(device, fqdd)
    if target is None:
        # Occupied device-type bay (a hand-entered module)?
        match = _FQDD_RE.match(fqdd or "")
        occupied = []
        if match:
            kind, number = match.group(1).lower(), int(match.group(2))
            for pattern in _BAY_POSITION_PATTERNS[kind]:
                occupied = [
                    bay
                    for bay in ModuleBay.objects.filter(
                        device=device, installed_module__isnull=False
                    ).exclude(name__startswith=_NIC_BAY_PREFIX)
                    if (m := pattern.match((bay.position or "").strip()))
                    and int(m.group(1)) == number
                ]
                if occupied:
                    break
        if len(occupied) == 1:
            bay = occupied[0]
            occupant = bay.installed_module
            if _is_plugin_module(occupant) or _module_holds_data(occupant):
                _log.warning(
                    f"Module bay '{bay.name}' on {device} already holds "
                    f"'{occupant}' with cabled/addressed interfaces; keeping "
                    f"it and syncing {fqdd} into a separate bay."
                )
            else:
                _log.info(
                    f"Replacing hand-entered module '{occupant}' in "
                    f"'{bay.name}' on {device} by the adapter iDRAC reports "
                    f"there ({fqdd})."
                )
                occupant.delete()
                bay.refresh_from_db()
                target = bay

    if target is not None:
        # Move a module a previous sync left in a plugin-named bay, so its
        # interfaces (cables, IPs) come along instead of being recreated.
        if current is not None:
            current.module_bay = target
            current.save()
            _log.info(
                f"Moved {fqdd} on {device} into device-type bay "
                f"'{target.name}'."
            )
        return target

    bay, _ = ModuleBay.objects.get_or_create(device=device, name=fqdd)
    return bay


def _sync_network_adapters(server, client, _log) -> tuple[int, int]:
    """
    Model each Dell network adapter as a NetBox ``Module`` in a ``ModuleBay``
    on the device, and each physical port as an ``Interface`` (MAC + LLDP).

    The module goes into the device-type bay for its slot when the type
    defines one (see _bay_for_adapter), else into a bay named after the
    adapter FQDD.

    Returns ``(modules_synced, interfaces_synced)``.
    """
    from dcim.choices import ModuleStatusChoices
    from dcim.models import Interface, Module, ModuleBay, ModuleType
    from django.contrib.contenttypes.models import ContentType

    device = server.device
    iface_ct = ContentType.objects.get_for_model(Interface)
    adapters = _safe_call(client.get_network_adapters, "network adapters")

    # Nothing reported at all is more likely a transient getter failure than
    # a server with zero NICs: keep the existing modules/interfaces rather
    # than wiping them (mirrors the component-reconciliation guard).
    if not adapters:
        return 0, 0

    modules_synced = interfaces_synced = 0
    desired_bays: set[int] = set()

    for adapter in adapters:
        name = adapter.get("name")
        if not name:
            continue

        mtype, _ = ModuleType.objects.get_or_create(
            manufacturer=get_or_create_manufacturer(
                adapter.get("manufacturer") or "Unknown"
            ),
            # A reusable hardware model (resolved by the client), never the
            # per-slot FQDD, so identical cards share one ModuleType.
            model=adapter.get("model") or name,
            defaults={"part_number": adapter.get("part_number", "")},
        )
        part_number = adapter.get("part_number", "")
        if part_number and mtype.part_number != part_number:
            mtype.part_number = part_number
            mtype.save(update_fields=["part_number"])

        bay = _bay_for_adapter(device, name, _log)
        desired_bays.add(bay.pk)
        numa_node = adapter.get("numa_node", "")
        if bay.custom_field_data.get("numa_node") != numa_node:
            bay.custom_field_data["numa_node"] = numa_node
            bay.save()
        Module.objects.update_or_create(
            module_bay=bay,
            defaults={
                "device": device,
                "module_type": mtype,
                "status": ModuleStatusChoices.STATUS_ACTIVE,
                "serial": (adapter.get("serial") or "")[:50],
            },
        )
        module = bay.installed_module
        modules_synced += 1

        desired_ports: set[str] = set()
        for port in adapter.get("ports", []):
            if not port.get("name"):
                continue
            desired_ports.add(port["name"])
            if _sync_interface(device, module, port, iface_ct, _log):
                interfaces_synced += 1

        # Drop interfaces on this module the adapter no longer reports.
        # Deleting an interface also removes its cable and IP assignments,
        # so skip when the adapter reported no ports at all or when a port
        # could not be read (a transient failure, not a removed port).
        if desired_ports and adapter.get("ports_complete", True):
            stale_ifaces = Interface.objects.filter(module=module).exclude(
                name__in=desired_ports
            )
            for iface in stale_ifaces:
                _log.warning(
                    f"Removing interface '{iface}' on {device}: no longer "
                    "reported by iDRAC (cable/IP assignments are removed "
                    "with it)."
                )
                iface.delete()

    # An adapter that could not be read is not a removed adapter: skip the
    # cleanup rather than delete modules (and their cables/IPs) on a partial
    # read. ``is False`` so a client without the attribute counts as complete.
    if getattr(client, "network_adapters_complete", True) is False:
        _log.warning(
            f"Network adapter inventory of {device} is partial (iDRAC read "
            "errors); not removing any module this time."
        )
        return modules_synced, interfaces_synced

    # Adapters that are gone: drop plugin-named bays with their module, and
    # empty device-type bays of the modules the sync had put there (the bay
    # itself belongs to the model and stays). Hand-entered modules are kept.
    for bay in ModuleBay.objects.filter(device=device).exclude(pk__in=desired_bays):
        module = Module.objects.filter(module_bay=bay).first()
        if bay.name.startswith(_NIC_BAY_PREFIX):
            _log.warning(
                f"Removing module bay '{bay.name}' on {device}: adapter no "
                "longer reported by iDRAC."
            )
            if module:
                module.delete()
            bay.delete()
        elif module and _is_plugin_module(module):
            _log.warning(
                f"Removing module '{module}' from bay '{bay.name}' on {device}: "
                "adapter no longer reported by iDRAC."
            )
            module.delete()

    return modules_synced, interfaces_synced


def _sync_idrac_management(device, net: dict, _log) -> None:
    """
    Model the iDRAC itself: a mgmt-only Interface on the device with its MAC
    and IPv4 address, set as the device's out-of-band (``oob_ip``).

    Matched by MAC address first (when iDRAC reports one), falling back to
    the literal name ``"iDRAC"``. This lets a device that already had a
    management interface before being onboarded to the plugin — named
    however the previous tooling/admin chose (e.g. "iDRAC9", "iDRAC9 1") —
    get reconciled onto that existing interface in place, rather than
    getting a second interface carrying a second copy of the same IP.
    The matched interface keeps its name: unlike the NIC ports there is only
    one management interface, so an admin-chosen name is left alone.
    """
    from dcim.choices import InterfaceTypeChoices
    from dcim.models import Interface, MACAddress
    from django.contrib.contenttypes.models import ContentType
    from ipam.models import IPAddress

    address = net.get("ipv4")
    if not address:
        return

    iface_ct = ContentType.objects.get_for_model(Interface)
    mac = (net.get("mac_address") or "").upper()

    iface = _match_interface_by_mac(device, mac, iface_ct)

    if iface is None:
        iface, _ = Interface.objects.get_or_create(
            device=device,
            name="iDRAC",
            defaults={
                "type": InterfaceTypeChoices.TYPE_1GE_FIXED,
                "mgmt_only": True,
            },
        )

    if not iface.mgmt_only:
        iface.mgmt_only = True
        iface.save(update_fields=["mgmt_only"])

    if mac:
        macobj, _ = MACAddress.objects.get_or_create(
            mac_address=mac,
            assigned_object_type=iface_ct,
            assigned_object_id=iface.pk,
        )
        if iface.primary_mac_address_id != macobj.pk:
            iface.primary_mac_address = macobj
            iface.save(update_fields=["primary_mac_address"])

    # Move an existing copy of this address onto the matched interface rather
    # than creating a second one: NetBox does not enforce global uniqueness by
    # default, so a blind get_or_create keyed on the interface would silently
    # leave the same iDRAC address recorded twice on the same device.
    cidr = f"{address}/{net.get('prefix_length') or 32}"
    device_iface_ids = list(
        Interface.objects.filter(device=device).values_list("pk", flat=True)
    )
    ip = (
        IPAddress.objects.filter(
            address=cidr,
            assigned_object_type=iface_ct,
            assigned_object_id__in=device_iface_ids,
        )
        .order_by("pk")
        .first()
    )
    if ip is None:
        ip = IPAddress.objects.create(
            address=cidr,
            assigned_object_type=iface_ct,
            assigned_object_id=iface.pk,
        )
    elif ip.assigned_object_id != iface.pk:
        ip.assigned_object_id = iface.pk
        ip.save(update_fields=["assigned_object_id"])

    if device.oob_ip_id != ip.pk:
        device.oob_ip = ip
        device.save(update_fields=["oob_ip"])
        _log.info(f"Set iDRAC OOB IP {cidr} on {device}")

    # Now that the address (and MAC) live on the matched interface, a plain
    # "iDRAC" interface left behind by an earlier sync is empty and can go.
    if iface.name != "iDRAC":
        leftover = (
            Interface.objects.filter(device=device, name="iDRAC")
            .exclude(pk=iface.pk)
            .first()
        )
        if leftover is not None and not _interface_carries_data(leftover):
            _drop_leftover_interface(
                leftover, _log, f"'{iface}' holds the iDRAC MAC and address.",
            )

    # Extra copies of the same address elsewhere on the device are left alone:
    # an IPAddress may carry a DNS name, tenant or description a human
    # entered, so it is reported rather than deleted.
    for extra in IPAddress.objects.filter(
        address=cidr,
        assigned_object_type=iface_ct,
        assigned_object_id__in=device_iface_ids,
    ).exclude(pk=ip.pk):
        _log.warning(
            f"{device} has a second copy of {cidr} on interface "
            f"'{extra.assigned_object}' (left over from an earlier sync). "
            "Delete it by hand once you've checked it holds nothing you "
            "need."
        )


# ---------------------------------------------------------------------------
# Server / device field updates
# ---------------------------------------------------------------------------


def _update_server_fields(server, system_info: dict, idrac_fw: str) -> None:
    """Apply iDRAC system info onto the DellServer (in memory)."""
    server.service_tag = system_info.get("service_tag") or server.service_tag
    server.model = system_info.get("model") or server.model
    server.bios_version = system_info.get("bios_version") or server.bios_version
    server.idrac_firmware = idrac_fw or server.idrac_firmware
    server.health = HealthChoices.from_redfish(system_info.get("health"))
    server.sync_status = SyncStatusChoices.STATUS_SYNCED
    server.sync_message = ""
    server.last_synced = timezone.now()


def _update_device(server, _log) -> None:
    """
    Best-effort propagation of iDRAC facts to the linked Device: service tag
    -> serial and reported model -> device type. Kept outside the main
    transaction so a device hiccup never discards the collected inventory.
    """
    device = server.device
    if _config("update_device_serial") and server.service_tag:
        try:
            _warn_on_duplicate_serial(device, server.service_tag, _log)
            device.serial = server.service_tag
            device.save(update_fields=["serial"])
        except Exception as exc:
            _log.warning(f"Could not update device serial: {exc}")
    if server.model:
        try:
            _set_device_type(device, server.model, _log)
        except Exception as exc:
            _log.warning(f"Could not set device type: {exc}")
    try:
        _ensure_template_bays(device, _log)
    except Exception as exc:
        _log.warning(f"Could not create device-type module bays: {exc}")


def _warn_on_duplicate_serial(device, service_tag: str, _log) -> None:
    """
    Warn if another device already carries this service tag as its serial.

    NetBox does not enforce serial uniqueness, so this only surfaces a likely
    duplicate (e.g. the machine was already onboarded by another tool); the
    plugin does not auto-merge devices.
    """
    from dcim.models import Device

    clash = (
        Device.objects.filter(serial=service_tag)
        .exclude(pk=device.pk)
        .first()
    )
    if clash:
        _log.warning(
            f"Service tag '{service_tag}' is already on device '{clash}'; "
            f"'{device}' may be a duplicate. Consider attaching the Dell "
            "server to the existing device instead."
        )


def _mark_failed(server, exc: Exception, _log) -> None:
    """Persist a FAILED sync status before the error propagates."""
    try:
        server.sync_status = SyncStatusChoices.STATUS_FAILED
        server.sync_message = str(exc)
        server.last_synced = timezone.now()
        server.save(
            update_fields=["sync_status", "sync_message", "last_synced"]
        )
    except Exception as save_exc:
        _log.error(f"Could not save FAILED status for {server}: {save_exc}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def sync_server(
    server: DellServer,
    *,
    client: IdracClient | None = None,
    logger=None,
) -> dict:
    """
    Synchronise a single ``DellServer`` from iDRAC and persist the results.

    Parameters
    ----------
    server:
        The ``DellServer`` to sync.
    client:
        A pre-built ``IdracClient`` to use instead of connecting from the
        server's credentials (used by tests to inject a fake).
    logger:
        A ``logging.Logger``-like object; defaults to this module's logger.

    Returns a summary dict (see ``message`` and the per-category counts).

    On any error the server row is saved with ``sync_status=FAILED`` and the
    exception is re-raised so the calling job is marked errored.
    """
    _log = logger or log
    own_client = client is None
    try:
        if own_client:
            check_address_allowed(
                server.idrac_address, _config("allowed_networks") or []
            )
            username, password = resolve_credentials(server)
            client = IdracClient(
                server.idrac_address,
                username,
                password,
                verify_ssl=_config("idrac_verify_ssl"),
                timeout=int(_config("idrac_timeout")),
            )

        _log.info(
            f"Sync {server} (iDRAC {server.idrac_address}): fetching "
            "inventory…"
        )
        # Network I/O happens before the DB transaction.
        system_info = client.get_system_info()
        idrac_fw = client.get_idrac_firmware()
        rows = _build_component_rows(client)
        idrac_net = (
            client.get_idrac_network()
            if _config("manage_idrac_interface")
            else {}
        )

        _update_server_fields(server, system_info, idrac_fw)
        _update_device(server, _log)  # best-effort, outside the transaction

        with transaction.atomic():
            created, updated, deleted = _reconcile_components(server, rows, _log)
            modules, interfaces = _sync_network_adapters(server, client, _log)
            if idrac_net:
                _sync_idrac_management(server.device, idrac_net, _log)
            server.save()

        message = (
            f"Sync successful: {created} created, {updated} updated, "
            f"{deleted} deleted; {modules} network modules, "
            f"{interfaces} interfaces."
        )
        _log.info(f"{server} — {message}")
        return {
            "ok": True,
            "components_created": created,
            "components_updated": updated,
            "components_deleted": deleted,
            "network_modules": modules,
            "network_interfaces": interfaces,
            "message": message,
        }

    except Exception as exc:
        _log.error(f"Sync failed for {server}: {exc}")
        _mark_failed(server, exc, _log)
        raise

    finally:
        if own_client and client is not None:
            client.close()
