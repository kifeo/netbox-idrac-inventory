"""
iDRAC fleet discovery: probe a DellScanRange and import reachable servers.

For each target IP the discovery connects to the iDRAC, then either attaches a
DellServer to an existing Device matching the service tag (no duplicate) or
creates a new Device (using the range's site/role), and finally syncs it.
"""

from __future__ import annotations

import logging
import os

from django.utils import timezone

from netbox.plugins import get_plugin_config

from netbox_idrac_inventory.idrac.client import IdracClient
from netbox_idrac_inventory.idrac.sync import PLUGIN_NAME, sync_server
from netbox_idrac_inventory.utils import expand_targets

log = logging.getLogger(__name__)


def _credentials(scan_range) -> tuple[str, str]:
    from netbox_idrac_inventory.utils import decrypt_secret

    username = scan_range.idrac_username or get_plugin_config(
        PLUGIN_NAME, "idrac_default_username"
    )
    password = (
        decrypt_secret(scan_range.idrac_password)
        or os.environ.get("IDRAC_DEFAULT_PASSWORD")
        or get_plugin_config(PLUGIN_NAME, "idrac_default_password")
    )
    return username, password


def discover_range(scan_range, *, logger=None) -> dict:
    """Probe every target in *scan_range* and import the reachable iDRACs."""
    from dcim.models import Device, DeviceType

    from netbox_idrac_inventory.models import DellServer
    from netbox_idrac_inventory.utils import (
        default_device_name,
        get_or_create_manufacturer,
    )

    _log = logger or log
    username, password = _credentials(scan_range)
    verify_ssl = get_plugin_config(PLUGIN_NAME, "idrac_verify_ssl")
    timeout = int(get_plugin_config(PLUGIN_NAME, "idrac_timeout"))
    manage_oob = get_plugin_config(PLUGIN_NAME, "manage_idrac_interface")

    try:
        targets = expand_targets(scan_range.targets)
    except ValueError as exc:
        _record(scan_range, f"Invalid targets: {exc}")
        raise

    created = linked = synced = unreachable = failed = skipped = 0

    for ip in targets:
        if DellServer.objects.filter(idrac_address=ip).exists():
            skipped += 1  # already managed
            continue

        client = IdracClient(
            ip, username, password, verify_ssl=verify_ssl, timeout=timeout
        )
        try:
            info = client.get_system_info()
            net = client.get_idrac_network() if manage_oob else {}
        except Exception as exc:
            unreachable += 1
            _log.info("Discovery: %s unreachable: %s", ip, exc)
            client.close()
            continue

        try:
            service_tag = (info.get("service_tag") or "").strip()
            # Prefer attaching to an existing device with the same service tag
            # (handles machines already onboarded by another tool).
            device = (
                Device.objects.filter(serial=service_tag).first()
                if service_tag else None
            )
            if device:
                linked += 1
            else:
                name = (
                    default_device_name(net.get("fqdn") or info.get("host_name"))
                    or service_tag
                    or ip
                )
                dtype, _ = DeviceType.objects.get_or_create(
                    manufacturer=get_or_create_manufacturer("Dell"),
                    model="Unknown",
                    defaults={"slug": "dell-unknown"},
                )
                device = Device.objects.create(
                    name=name,
                    site=scan_range.site,
                    role=scan_range.role,
                    device_type=dtype,
                )
                created += 1

            server, _ = DellServer.objects.get_or_create(
                device=device,
                defaults={
                    "idrac_address": ip,
                    "idrac_username": scan_range.idrac_username,
                },
            )
            # Reuse the open client for the initial sync.
            sync_server(server, client=client, logger=_log)
            synced += 1
        except Exception as exc:
            failed += 1
            _log.warning("Discovery: import failed for %s: %s", ip, exc)
        finally:
            client.close()

    message = (
        f"Scanned {len(targets)} targets: {created} created, {linked} linked, "
        f"{synced} synced, {skipped} already managed, {unreachable} "
        f"unreachable, {failed} failed."
    )
    _record(scan_range, message)
    _log.info("%s — %s", scan_range, message)
    return {
        "created": created,
        "linked": linked,
        "synced": synced,
        "skipped": skipped,
        "unreachable": unreachable,
        "failed": failed,
        "message": message,
    }


def _record(scan_range, message: str) -> None:
    scan_range.message = message
    scan_range.last_run = timezone.now()
    scan_range.save(update_fields=["message", "last_run"])
