# Tests for scan-range target expansion and the discovery engine.
from unittest.mock import MagicMock, patch

from django.test import TestCase

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site

from netbox_idrac_inventory.models import DellScanRange, DellServer
from netbox_idrac_inventory.utils import expand_targets


class ExpandTargetsTest(TestCase):
    def test_cidr_excludes_network_and_broadcast(self):
        ips = expand_targets("10.0.0.0/30")
        self.assertEqual(ips, ["10.0.0.1", "10.0.0.2"])

    def test_short_dashed_range(self):
        self.assertEqual(
            expand_targets("10.0.0.10-12"),
            ["10.0.0.10", "10.0.0.11", "10.0.0.12"],
        )

    def test_full_dashed_range_and_single_and_dedup(self):
        ips = expand_targets("10.0.0.1-10.0.0.2, 10.0.0.2 host.example.com")
        self.assertEqual(ips, ["10.0.0.1", "10.0.0.2", "host.example.com"])

    def test_limit_exceeded(self):
        with self.assertRaises(ValueError):
            expand_targets("10.0.0.0/8", limit=100)


class DiscoverRangeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="Disc", slug="disc")
        cls.role = DeviceRole.objects.create(name="Srv", slug="srv")

    def _range(self, targets="10.50.0.5"):
        return DellScanRange.objects.create(
            name="r", targets=targets, site=self.site, role=self.role,
        )

    def _fake_client(self, service_tag):
        client = MagicMock()
        client.get_system_info.return_value = {
            "service_tag": service_tag, "host_name": "disc-host",
        }
        client.get_idrac_network.return_value = {}
        return client

    def test_creates_device_for_new_host(self):
        from netbox_idrac_inventory.idrac.discovery import discover_range

        scan = self._range()
        with patch(
            "netbox_idrac_inventory.idrac.discovery.IdracClient",
            return_value=self._fake_client("NEWTAG1"),
        ), patch("netbox_idrac_inventory.idrac.discovery.sync_server"):
            result = discover_range(scan)

        self.assertEqual(result["created"], 1)
        server = DellServer.objects.get(idrac_address="10.50.0.5")
        self.assertEqual(server.device.name, "disc-host")

    def test_links_existing_device_by_service_tag(self):
        from netbox_idrac_inventory.idrac.discovery import discover_range

        mfr = Manufacturer.objects.create(name="Dell", slug="dell")
        dt = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450")
        existing = Device.objects.create(
            name="already-here", site=self.site, role=self.role,
            device_type=dt, serial="EXISTTAG")

        scan = self._range(targets="10.50.0.9")
        with patch(
            "netbox_idrac_inventory.idrac.discovery.IdracClient",
            return_value=self._fake_client("EXISTTAG"),
        ), patch("netbox_idrac_inventory.idrac.discovery.sync_server"):
            result = discover_range(scan)

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["linked"], 1)
        server = DellServer.objects.get(idrac_address="10.50.0.9")
        self.assertEqual(server.device, existing)

    def test_skips_already_managed(self):
        from netbox_idrac_inventory.idrac.discovery import discover_range

        mfr = Manufacturer.objects.create(name="Dell", slug="dell")
        dt = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450")
        dev = Device.objects.create(
            name="managed", site=self.site, role=self.role, device_type=dt)
        DellServer.objects.create(device=dev, idrac_address="10.50.0.5")

        scan = self._range(targets="10.50.0.5")
        with patch(
            "netbox_idrac_inventory.idrac.discovery.IdracClient"
        ) as mock_client:
            result = discover_range(scan)

        mock_client.assert_not_called()  # never probed
        self.assertEqual(result["skipped"], 1)
