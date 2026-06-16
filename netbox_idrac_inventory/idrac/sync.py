"""
Mapping and synchronisation engine for Dell iDRAC -> NetBox.

This module is framework-aware (Django ORM, NetBox models) but contains no
view or form logic. It is callable from a background job, a management
command, or unit tests (pass a ``client`` fixture to bypass the real iDRAC).

Password security note
----------------------
The iDRAC password is resolved at sync time from the plugin config
(``idrac_default_password``) or the ``IDRAC_DEFAULT_PASSWORD`` environment
variable. It is never stored in the database.
"""

from __future__ import annotations

import logging
import os
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
from netbox_idrac_inventory.utils import get_or_create_manufacturer

if TYPE_CHECKING:
    from netbox_idrac_inventory.models import DellServer

log = logging.getLogger(__name__)

PLUGIN_NAME = "netbox_idrac_inventory"

# LLDP custom-field names (created via post_migrate, see signals.py).
CF_LLDP_CHASSIS = "lldp_remote_chassis"
CF_LLDP_PORT = "lldp_remote_port"

# Module bays the plugin manages are named after the Dell adapter FQDD, which
# always starts with this prefix; used to scope reconciliation/deletion.
_NIC_BAY_PREFIX = "NIC."


def _config(key: str):
    """Read a plugin setting (falls back to PluginConfig.default_settings)."""
    return get_plugin_config(PLUGIN_NAME, key)


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


def resolve_credentials(server: "DellServer") -> tuple[str, str]:
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
                "Skipping %s component with empty name.", row["component_type"]
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
    from django.utils.text import slugify

    from dcim.models import DeviceType

    dtype, _ = DeviceType.objects.get_or_create(
        manufacturer=get_or_create_manufacturer("Dell"),
        model=model,
        defaults={"slug": slugify(model)[:100]},
    )
    if device.device_type_id != dtype.pk:
        device.device_type = dtype
        device.save(update_fields=["device_type"])
        _log.info("Set device '%s' type to '%s'.", device, model)


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


def _sync_interface(device, module, port: dict, iface_ct) -> None:
    """Upsert a single Interface (type, MAC, LLDP) for one adapter port."""
    from dcim.models import Interface, MACAddress

    itype = _interface_type_for_speed(port.get("speed_mbps"))
    iface, _ = Interface.objects.get_or_create(
        device=device,
        name=port["name"],
        defaults={"type": itype, "module": module},
    )

    changed = False
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

    mac = (port.get("mac_address") or "").upper()
    if mac:
        macobj, _ = MACAddress.objects.get_or_create(
            mac_address=mac,
            assigned_object_type=iface_ct,
            assigned_object_id=iface.pk,
        )
        if iface.primary_mac_address_id != macobj.pk:
            iface.primary_mac_address = macobj
            iface.save(update_fields=["primary_mac_address"])


def _sync_network_adapters(server, client, _log) -> tuple[int, int]:
    """
    Model each Dell network adapter as a NetBox ``Module`` in a ``ModuleBay``
    on the device, and each physical port as an ``Interface`` (MAC + LLDP).

    Returns ``(modules_synced, interfaces_synced)``.
    """
    from django.contrib.contenttypes.models import ContentType

    from dcim.choices import ModuleStatusChoices
    from dcim.models import Interface, Module, ModuleBay, ModuleType

    device = server.device
    iface_ct = ContentType.objects.get_for_model(Interface)
    adapters = _safe_call(client.get_network_adapters, "network adapters")

    modules_synced = interfaces_synced = 0
    desired_bays: set[str] = set()

    for adapter in adapters:
        name = adapter.get("name")
        if not name:
            continue
        desired_bays.add(name)

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

        bay, _ = ModuleBay.objects.get_or_create(device=device, name=name)
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
            _sync_interface(device, module, port, iface_ct)
            interfaces_synced += 1

        # Drop interfaces on this module the adapter no longer reports.
        Interface.objects.filter(module=module).exclude(
            name__in=desired_ports
        ).delete()

    # Drop plugin-managed bays (with their modules/interfaces) for adapters
    # that are gone.
    stale_bays = ModuleBay.objects.filter(
        device=device, name__startswith=_NIC_BAY_PREFIX
    ).exclude(name__in=desired_bays)
    for bay in stale_bays:
        Module.objects.filter(module_bay=bay).delete()
        bay.delete()

    return modules_synced, interfaces_synced


def _sync_idrac_management(device, net: dict, _log) -> None:
    """
    Model the iDRAC itself: a mgmt-only ``iDRAC`` Interface on the device with
    its MAC and IPv4 address, set as the device's out-of-band (``oob_ip``).
    """
    from django.contrib.contenttypes.models import ContentType

    from dcim.choices import InterfaceTypeChoices
    from dcim.models import Interface, MACAddress
    from ipam.models import IPAddress

    address = net.get("ipv4")
    if not address:
        return

    iface_ct = ContentType.objects.get_for_model(Interface)

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

    mac = (net.get("mac_address") or "").upper()
    if mac:
        macobj, _ = MACAddress.objects.get_or_create(
            mac_address=mac,
            assigned_object_type=iface_ct,
            assigned_object_id=iface.pk,
        )
        if iface.primary_mac_address_id != macobj.pk:
            iface.primary_mac_address = macobj
            iface.save(update_fields=["primary_mac_address"])

    cidr = f"{address}/{net.get('prefix_length') or 32}"
    ip, _ = IPAddress.objects.get_or_create(
        address=cidr,
        assigned_object_type=iface_ct,
        assigned_object_id=iface.pk,
    )
    if device.oob_ip_id != ip.pk:
        device.oob_ip = ip
        device.save(update_fields=["oob_ip"])
        _log.info("Set iDRAC OOB IP %s on %s", cidr, device)


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
            _log.warning("Could not update device serial: %s", exc)
    if server.model:
        try:
            _set_device_type(device, server.model, _log)
        except Exception as exc:
            _log.warning("Could not set device type: %s", exc)


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
            "Service tag '%s' is already on device '%s'; '%s' may be a "
            "duplicate. Consider attaching the Dell server to the existing "
            "device instead.",
            service_tag, clash, device,
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
        _log.error("Could not save FAILED status for %s: %s", server, save_exc)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def sync_server(
    server: "DellServer",
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
            username, password = resolve_credentials(server)
            client = IdracClient(
                server.idrac_address,
                username,
                password,
                verify_ssl=_config("idrac_verify_ssl"),
                timeout=int(_config("idrac_timeout")),
            )

        _log.info(
            "Sync %s (iDRAC %s): fetching inventory…",
            server,
            server.idrac_address,
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
        _log.info("%s — %s", server, message)
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
        _log.error("Sync failed for %s: %s", server, exc)
        _mark_failed(server, exc, _log)
        raise

    finally:
        if own_client and client is not None:
            client.close()
