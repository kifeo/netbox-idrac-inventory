# Model unit tests for netbox_idrac_inventory.
#
# These tests must run inside a real NetBox Django environment where all
# app dependencies (dcim, extras, etc.) are available.

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site

from netbox_idrac_inventory.choices import ComponentTypeChoices, SyncStatusChoices
from netbox_idrac_inventory.models import DellComponent, DellServer


def _make_device(name: str = "test-server-01") -> Device:
    """Create a minimal Device sufficient for FK constraints."""
    site, _ = Site.objects.get_or_create(name="Test Site", slug="test-site")
    manufacturer, _ = Manufacturer.objects.get_or_create(
        name="Dell", slug="dell"
    )
    device_type, _ = DeviceType.objects.get_or_create(
        manufacturer=manufacturer,
        model="PowerEdge R740",
        slug="poweredge-r740",
    )
    role, _ = DeviceRole.objects.get_or_create(
        name="Server", slug="server"
    )
    device = Device.objects.create(
        name=name,
        site=site,
        device_type=device_type,
        role=role,
    )
    return device


class DellServerModelTest(TestCase):
    """Tests for DellServer model creation, defaults, and __str__."""

    def setUp(self):
        self.device = _make_device("dell-r740-01")

    def test_create_minimal(self):
        """DellServer can be created with only the required device and idrac_address."""
        server = DellServer.objects.create(
            device=self.device,
            idrac_address="192.168.1.10",
        )
        self.assertEqual(server.sync_status, SyncStatusChoices.STATUS_NEW)
        self.assertIsNone(server.last_synced)

    def test_str_with_service_tag(self):
        server = DellServer.objects.create(
            device=self.device,
            idrac_address="192.168.1.10",
            service_tag="ABC1234",
        )
        self.assertIn("ABC1234", str(server))

    def test_str_fallback_to_idrac_address(self):
        """When service_tag is blank, __str__ falls back to idrac_address."""
        server = DellServer.objects.create(
            device=self.device,
            idrac_address="idrac.example.com",
        )
        self.assertIn("idrac.example.com", str(server))

    def test_device_onetoone_unique(self):
        """A second DellServer for the same device must fail."""
        DellServer.objects.create(
            device=self.device,
            idrac_address="192.168.1.10",
        )
        device2 = _make_device("dell-r740-02")
        # Reuse the same device — must violate OneToOne
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DellServer.objects.create(
                    device=self.device,
                    idrac_address="192.168.1.11",
                )

    def test_get_absolute_url(self):
        server = DellServer.objects.create(
            device=self.device,
            idrac_address="192.168.1.10",
        )
        url = server.get_absolute_url()
        self.assertIn(str(server.pk), url)


class DellComponentModelTest(TestCase):
    """Tests for DellComponent creation and unique constraint."""

    def setUp(self):
        device = _make_device("dell-r740-comp")
        self.server = DellServer.objects.create(
            device=device,
            idrac_address="10.0.0.1",
        )

    def test_create_component(self):
        comp = DellComponent.objects.create(
            server=self.server,
            component_type=ComponentTypeChoices.TYPE_CPU,
            name="CPU.Socket.1",
            manufacturer="Intel",
            model="Xeon Gold 6226R",
        )
        self.assertEqual(comp.server, self.server)
        self.assertEqual(comp.component_type, ComponentTypeChoices.TYPE_CPU)

    def test_str(self):
        comp = DellComponent(
            server=self.server,
            component_type=ComponentTypeChoices.TYPE_MEMORY,
            name="DIMM.Slot.A1",
        )
        s = str(comp)
        # __str__ returns "<verbose component type>: <name>"
        self.assertIn("DIMM.Slot.A1", s)

    def test_unique_constraint(self):
        """(server, component_type, name) must be unique per server."""
        DellComponent.objects.create(
            server=self.server,
            component_type=ComponentTypeChoices.TYPE_DISK,
            name="Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DellComponent.objects.create(
                    server=self.server,
                    component_type=ComponentTypeChoices.TYPE_DISK,
                    name="Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1",
                )

    def test_unique_constraint_different_server(self):
        """Same (component_type, name) on a different server must succeed."""
        device2 = _make_device("dell-r740-comp2")
        server2 = DellServer.objects.create(
            device=device2,
            idrac_address="10.0.0.2",
        )
        DellComponent.objects.create(
            server=self.server,
            component_type=ComponentTypeChoices.TYPE_NIC,
            name="NIC.Slot.1-1",
        )
        # Same name+type on different server is allowed.
        comp2 = DellComponent.objects.create(
            server=server2,
            component_type=ComponentTypeChoices.TYPE_NIC,
            name="NIC.Slot.1-1",
        )
        self.assertNotEqual(comp2.server, self.server)

    def test_data_default_is_empty_dict(self):
        comp = DellComponent.objects.create(
            server=self.server,
            component_type=ComponentTypeChoices.TYPE_PSU,
            name="PSU.Slot.1",
        )
        self.assertEqual(comp.data, {})
