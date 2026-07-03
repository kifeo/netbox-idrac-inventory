# Unit tests for the iDRAC sync engine.
#
# These tests inject a fake client object into sync_server() so no live
# iDRAC is required.  They verify:
#   1. DellServer scalar fields are updated from system-info.
#   2. Components are created for each hardware category.
#   3. A second sync with a component removed deletes the orphaned row.
#
# The sync_server() signature is:
#   sync_server(server, *, client=None, logger=None) -> dict
#
# The fake client mirrors the interface the real IdracClient exposes.

import logging
from unittest.mock import MagicMock, patch

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from django.test import TestCase

from netbox_idrac_inventory.choices import ComponentTypeChoices, SyncStatusChoices
from netbox_idrac_inventory.models import DellComponent, DellServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_server(name: str = "sync-test-01", idrac: str = "10.0.1.1") -> DellServer:
    site, _ = Site.objects.get_or_create(name="Sync Test Site", slug="sync-test-site")
    mfr, _ = Manufacturer.objects.get_or_create(name="Dell EMC", slug="dell-emc")
    dt, _ = DeviceType.objects.get_or_create(
        manufacturer=mfr, model="PowerEdge R640", slug="poweredge-r640"
    )
    role, _ = DeviceRole.objects.get_or_create(name="Compute", slug="compute")
    device = Device.objects.create(name=name, site=site, device_type=dt, role=role)
    return DellServer.objects.create(device=device, idrac_address=idrac)


def _make_fake_client(
    *,
    processors=None,
    memory=None,
    storage_controllers=None,
    drives=None,
    power_supplies=None,
    network_adapters=None,
    firmware=None,
):
    """Build a fake IdracClient with canned responses for all methods."""

    client = MagicMock()

    # Network adapters default to empty so component-focused tests don't also
    # create Modules/Interfaces; the dedicated test passes explicit data.
    client.get_network_adapters.return_value = (
        network_adapters if network_adapters is not None else []
    )
    # No iDRAC management interface by default (empty dict -> skipped).
    client.get_idrac_network.return_value = {}
    # No UpdateService firmware inventory by default.
    client.get_firmware_inventory.return_value = (
        firmware if firmware is not None else []
    )

    # The real IdracClient returns NORMALIZED snake_case dicts (not raw
    # Redfish JSON), so the fakes must match that contract — see
    # netbox_idrac_inventory/idrac/client.py.

    # System-level info. "health" carries the raw Redfish value.
    client.get_system_info.return_value = {
        "service_tag": "ABCDE12",
        "model": "PowerEdge R640",
        "manufacturer": "Dell Inc.",
        "bios_version": "2.14.2",
        "power_state": "On",
        "host_name": "node-01",
        "health": "OK",
    }

    # iDRAC firmware: the real client returns a plain string.
    client.get_idrac_firmware.return_value = "5.10.30.00"

    # Hardware sub-collections
    client.get_processors.return_value = processors if processors is not None else [
        {
            "name": "CPU.Socket.1",
            "manufacturer": "Intel",
            "model": "Xeon Gold 6226R",
            "serial": "SN-CPU-1",
            "total_cores": 16,
            "total_threads": 32,
            "max_speed_mhz": 3900,
            "health": "OK",
        }
    ]
    client.get_memory.return_value = memory if memory is not None else [
        {
            "name": "DIMM.Slot.A1",
            "manufacturer": "Samsung",
            "model": "M393A4K40CB2-CVF",
            "part_number": "M393A4K40CB2-CVF",
            "serial": "SN-DIMM-1",
            "capacity_bytes": 34359738368,
            "speed_mhz": 2933,
            "memory_device_type": "DDR4",
        }
    ]
    client.get_storage_controllers.return_value = (
        storage_controllers
        if storage_controllers is not None
        else [
            {
                "name": "RAID.Integrated.1-1",
                "manufacturer": "DELL",
                "model": "PERC H730P Mini",
                "firmware": "25.5.0.0018",
                "serial": "",
            }
        ]
    )
    client.get_drives.return_value = drives if drives is not None else [
        {
            "name": "Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
            "manufacturer": "SEAGATE",
            "model": "ST1200MM0129",
            "serial": "SN-DISK-1",
            "part_number": "PN-DISK-1",
            "capacity_bytes": 1200000000000,
            "media_type": "HDD",
            "protocol": "SAS",
        }
    ]
    client.get_power_supplies.return_value = (
        power_supplies
        if power_supplies is not None
        else [
            {
                "name": "PSU.Slot.1",
                "manufacturer": "DELL",
                "model": "PWR SPLY 750W",
                "serial": "SN-PSU-1",
                "part_number": "PN-PSU-1",
                "power_capacity_watts": 750,
                "firmware": "00.0D.53",
            }
        ]
    )

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class SyncServerFieldsTest(TestCase):
    """sync_server() updates DellServer scalar fields from iDRAC system info."""

    def test_fields_updated(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server()
        fake = _make_fake_client()
        sync_server(server, client=fake, logger=logging.getLogger("test"))

        server.refresh_from_db()
        self.assertEqual(server.service_tag, "ABCDE12")
        self.assertEqual(server.model, "PowerEdge R640")
        self.assertEqual(server.bios_version, "2.14.2")
        self.assertEqual(server.idrac_firmware, "5.10.30.00")
        self.assertEqual(server.sync_status, SyncStatusChoices.STATUS_SYNCED)
        self.assertIsNotNone(server.last_synced)

    def test_returns_dict(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="sync-test-ret")
        fake = _make_fake_client()
        result = sync_server(server, client=fake)
        self.assertIsInstance(result, dict)


class SyncServerComponentCreationTest(TestCase):
    """Components are created for each hardware category returned by the client."""

    def test_components_created(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="sync-comp-01")
        fake = _make_fake_client()
        sync_server(server, client=fake)

        # 1 CPU, 1 DIMM, 1 controller, 1 disk, 1 PSU. NICs are NOT components
        # anymore (modelled as Modules/Interfaces), so no 'nic' rows here.
        comps = DellComponent.objects.filter(server=server)
        self.assertGreaterEqual(comps.count(), 5)
        self.assertEqual(
            comps.filter(component_type=ComponentTypeChoices.TYPE_NIC).count(),
            0,
        )

        cpu = comps.filter(component_type=ComponentTypeChoices.TYPE_CPU).first()
        self.assertIsNotNone(cpu)
        self.assertEqual(cpu.name, "CPU.Socket.1")

        disk = comps.filter(component_type=ComponentTypeChoices.TYPE_DISK).first()
        self.assertIsNotNone(disk)
        self.assertEqual(disk.capacity_bytes, 1200000000000)


class SyncServerReconcileTest(TestCase):
    """A second sync with fewer components removes the orphaned rows."""

    def test_removed_component_deleted(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="sync-recon-01")

        # First sync — two drives
        fake_v1 = _make_fake_client(
            drives=[
                {
                    "name": "Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
                    "manufacturer": "SEAGATE",
                    "model": "ST1200MM0129",
                    "serial": "SN-D1",
                    "capacity_bytes": 1_200_000_000_000,
                },
                {
                    "name": "Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1",
                    "manufacturer": "SEAGATE",
                    "model": "ST1200MM0129",
                    "serial": "SN-D2",
                    "capacity_bytes": 1_200_000_000_000,
                },
            ]
        )
        sync_server(server, client=fake_v1)

        disk_count_after_first = DellComponent.objects.filter(
            server=server, component_type=ComponentTypeChoices.TYPE_DISK
        ).count()
        self.assertEqual(disk_count_after_first, 2)

        # Second sync — only one drive (Bay.0 removed)
        fake_v2 = _make_fake_client(
            drives=[
                {
                    "name": "Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1",
                    "manufacturer": "SEAGATE",
                    "model": "ST1200MM0129",
                    "serial": "SN-D2",
                    "capacity_bytes": 1_200_000_000_000,
                },
            ]
        )
        sync_server(server, client=fake_v2)

        disk_count_after_second = DellComponent.objects.filter(
            server=server, component_type=ComponentTypeChoices.TYPE_DISK
        ).count()
        self.assertEqual(disk_count_after_second, 1)

        remaining = DellComponent.objects.get(
            server=server, component_type=ComponentTypeChoices.TYPE_DISK
        )
        self.assertEqual(remaining.name, "Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1")


class SyncServerIdempotentTest(TestCase):
    """Running sync twice with the same data must not duplicate components."""

    def test_idempotent(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="sync-idem-01")
        fake = _make_fake_client()

        sync_server(server, client=fake)
        count_after_first = DellComponent.objects.filter(server=server).count()

        sync_server(server, client=fake)
        count_after_second = DellComponent.objects.filter(server=server).count()

        self.assertEqual(count_after_first, count_after_second)


class SyncServerDeviceTypeTest(TestCase):
    """Sync replaces the placeholder device type with the iDRAC model."""

    def test_device_type_set_from_model(self):
        from dcim.models import DeviceType, Manufacturer

        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="dtype-01")
        # Start from a placeholder type different from the reported model.
        mfr, _ = Manufacturer.objects.get_or_create(name="Dell", slug="dell")
        placeholder, _ = DeviceType.objects.get_or_create(
            manufacturer=mfr, model="Unknown", slug="dell-unknown")
        server.device.device_type = placeholder
        server.device.save()

        # The fake client reports model "PowerEdge R640".
        sync_server(server, client=_make_fake_client())

        server.device.refresh_from_db()
        self.assertEqual(server.device.device_type.model, "PowerEdge R640")


class SyncHealthTest(TestCase):
    """Redfish health is mapped onto the server and its components."""

    def test_health_mapped(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="health-01")
        fake = _make_fake_client(
            power_supplies=[{
                "name": "PSU.Slot.2", "manufacturer": "DELL",
                "model": "PWR", "serial": "SN-PSU-2", "health": "Critical",
            }],
        )
        fake.get_system_info.return_value = {
            **fake.get_system_info.return_value, "health": "Critical",
        }
        sync_server(server, client=fake)

        server.refresh_from_db()
        self.assertEqual(server.health, "critical")
        cpu = server.components.get(component_type=ComponentTypeChoices.TYPE_CPU)
        self.assertEqual(cpu.health, "ok")
        psu = server.components.get(component_type=ComponentTypeChoices.TYPE_PSU)
        self.assertEqual(psu.health, "critical")


class SyncIdracManagementTest(TestCase):
    """The iDRAC's own NIC becomes a mgmt interface + the device's OOB IP."""

    def test_idrac_interface_and_oob_ip(self):
        from dcim.models import Interface

        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="oob-01")
        fake = _make_fake_client()
        fake.get_idrac_network.return_value = {
            "ipv4": "10.20.30.40",
            "prefix_length": 24,
            "gateway": "10.20.30.1",
            "mac_address": "AA:BB:CC:00:11:22",
            "hostname": "oob-01",
            "fqdn": "oob-01.ipmi.example.com",
            "speed_mbps": 1000,
        }
        sync_server(server, client=fake)

        device = server.device
        iface = Interface.objects.get(device=device, name="iDRAC")
        self.assertTrue(iface.mgmt_only)
        self.assertEqual(
            iface.primary_mac_address.mac_address, "AA:BB:CC:00:11:22"
        )
        device.refresh_from_db()
        self.assertEqual(str(device.oob_ip.address), "10.20.30.40/24")


class DellSyncAllJobTest(TestCase):
    """The recurring system job fans out one DellSyncJob per DellServer."""

    def test_enqueues_a_job_per_server(self):
        from netbox_idrac_inventory.jobs import DellSyncAllJob

        server_a = _make_server(name="all-1", idrac="10.0.9.1")
        server_b = _make_server(name="all-2", idrac="10.0.9.2")
        with patch(
            "netbox_idrac_inventory.jobs.DellSyncJob.enqueue"
        ) as mock_enqueue:
            DellSyncAllJob(MagicMock()).run()
        self.assertEqual(mock_enqueue.call_count, 2)
        enqueued = {c.kwargs["instance"] for c in mock_enqueue.call_args_list}
        self.assertEqual(enqueued, {server_a, server_b})


class SyncFirmwareInventoryTest(TestCase):
    """UpdateService firmware versions enrich matching components by FQDD."""

    def test_component_firmware_enriched(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="fw-01")
        fake = _make_fake_client(firmware=[
            # Matches the default storage controller fixture by FQDD.
            {
                "name": "PERC H730P Mini",
                "version": "25.5.9.0001",
                "fqdd": "RAID.Integrated.1-1",
            },
            # No component with this name: must be ignored, not crash.
            {"name": "System CPLD", "version": "1.0.6", "fqdd": "CPLD.Embedded.1"},
        ])
        sync_server(server, client=fake)

        ctrl = server.components.get(
            component_type=ComponentTypeChoices.TYPE_CONTROLLER
        )
        # FirmwareInventory is authoritative: it overrides the version the
        # controller resource itself reported (25.5.0.0018 in the fixture).
        self.assertEqual(ctrl.firmware, "25.5.9.0001")


class SyncAllowedNetworksTest(TestCase):
    """allowed_networks blocks a sync to an out-of-policy iDRAC address."""

    def test_out_of_range_address_fails_sync(self):
        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="allow-01", idrac="192.168.77.1")
        config = {
            "allowed_networks": ["10.0.0.0/8"],
            "idrac_verify_ssl": False,
            "idrac_timeout": 30,
            "manage_idrac_interface": False,
            "update_device_serial": True,
            "idrac_default_username": "root",
            "idrac_default_password": "pw",
        }
        with patch(
            "netbox_idrac_inventory.idrac.sync._config",
            side_effect=config.__getitem__,
        ):
            with self.assertRaises(ValueError):
                sync_server(server)

        server.refresh_from_db()
        self.assertEqual(server.sync_status, SyncStatusChoices.STATUS_FAILED)
        self.assertIn("allowed_networks", server.sync_message)


def _sample_adapters(*, second_port=True):
    """Two adapters; the first has 1-2 ports (the 2nd toggles for reconcile)."""
    ports = [
        {
            "name": "NIC.Integrated.1-1",
            "mac_address": "5C:6F:69:88:06:D0",
            "link_status": "Up",
            "speed_mbps": 10000,
            "lldp_remote_chassis": "switch-lab-01",
            "lldp_remote_port": "Ethernet1/5",
        }
    ]
    if second_port:
        ports.append(
            {
                "name": "NIC.Integrated.1-2",
                "mac_address": "5C:6F:69:88:06:D1",
                "link_status": "Down",
                "speed_mbps": 10000,
                "lldp_remote_chassis": "",
                "lldp_remote_port": "",
            }
        )
    return [
        {
            "name": "NIC.Integrated.1",
            "manufacturer": "Broadcom Inc.",
            "model": "BRCM 2P 10G SFP 57412S OCP NIC",
            "part_number": "0CP610",
            "serial": "VNFCVBA1CC00AJ",
            "firmware": "36.11.73.00",
            "ports": ports,
        }
    ]


class SyncNetworkAdaptersTest(TestCase):
    """Network adapters become Modules in ModuleBays; ports become Interfaces."""

    def test_modules_and_interfaces_created(self):
        from dcim.models import Interface, ModuleBay, ModuleType

        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="net-01")
        fake = _make_fake_client(network_adapters=_sample_adapters())
        sync_server(server, client=fake)

        device = server.device
        bay = ModuleBay.objects.get(device=device, name="NIC.Integrated.1")
        module = bay.installed_module
        self.assertIsNotNone(module)
        self.assertEqual(module.serial, "VNFCVBA1CC00AJ")

        mtype = ModuleType.objects.get(model="BRCM 2P 10G SFP 57412S OCP NIC")
        self.assertEqual(mtype.part_number, "0CP610")
        self.assertEqual(module.module_type, mtype)

        ifaces = Interface.objects.filter(device=device)
        self.assertEqual(ifaces.count(), 2)
        port1 = ifaces.get(name="NIC.Integrated.1-1")
        self.assertEqual(port1.module, module)
        self.assertEqual(port1.type, "10gbase-x-sfpp")
        self.assertEqual(
            port1.primary_mac_address.mac_address, "5C:6F:69:88:06:D0"
        )
        # LLDP neighbour stored in custom fields.
        self.assertEqual(
            port1.custom_field_data.get("lldp_remote_chassis"), "switch-lab-01"
        )
        self.assertEqual(
            port1.custom_field_data.get("lldp_remote_port"), "Ethernet1/5"
        )

    def test_removed_port_is_deleted(self):
        from dcim.models import Interface

        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="net-recon-01")

        sync_server(server, client=_make_fake_client(
            network_adapters=_sample_adapters(second_port=True)))
        self.assertEqual(Interface.objects.filter(device=server.device).count(), 2)

        # Second sync reports only one port -> the other interface is removed.
        sync_server(server, client=_make_fake_client(
            network_adapters=_sample_adapters(second_port=False)))
        names = set(
            Interface.objects.filter(device=server.device)
            .values_list("name", flat=True)
        )
        self.assertEqual(names, {"NIC.Integrated.1-1"})

    def test_empty_adapter_list_does_not_wipe(self):
        """A sync where iDRAC reports no adapters (likely a transient getter
        failure) must keep the existing modules and interfaces."""
        from dcim.models import Interface, ModuleBay

        from netbox_idrac_inventory.idrac.sync import sync_server

        server = _make_server(name="net-guard-01")

        sync_server(server, client=_make_fake_client(
            network_adapters=_sample_adapters()))
        self.assertEqual(Interface.objects.filter(device=server.device).count(), 2)

        sync_server(server, client=_make_fake_client(network_adapters=[]))
        self.assertEqual(Interface.objects.filter(device=server.device).count(), 2)
        self.assertTrue(
            ModuleBay.objects.filter(
                device=server.device, name="NIC.Integrated.1"
            ).exists()
        )
