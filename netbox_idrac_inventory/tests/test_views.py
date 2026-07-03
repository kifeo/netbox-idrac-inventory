# Tests for the list-view bulk sync action.
from unittest.mock import patch

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from netbox_idrac_inventory.models import DellServer


class DellServerBulkSyncViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        site = Site.objects.create(name="Bulk", slug="bulk")
        role = DeviceRole.objects.create(name="Srv", slug="srv")
        mfr = Manufacturer.objects.create(name="Dell", slug="dell")
        dtype = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450"
        )
        cls.servers = [
            DellServer.objects.create(
                device=Device.objects.create(
                    name=f"bulk-{i}", site=site, role=role, device_type=dtype
                ),
                idrac_address=f"10.60.0.{i}",
            )
            for i in (1, 2, 3)
        ]
        cls.user = get_user_model().objects.create_superuser(
            username="bulk-admin"
        )

    def test_bulk_sync_enqueues_selected_servers(self):
        self.client.force_login(self.user)
        url = reverse("plugins:netbox_idrac_inventory:dellserver_bulk_sync")
        selected = [self.servers[0].pk, self.servers[2].pk]
        with patch("netbox_idrac_inventory.views.enqueue_sync") as mock_enqueue:
            response = self.client.post(url, {"pk": selected})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mock_enqueue.call_count, 2)
        synced = {c.args[0].pk for c in mock_enqueue.call_args_list}
        self.assertEqual(synced, set(selected))
