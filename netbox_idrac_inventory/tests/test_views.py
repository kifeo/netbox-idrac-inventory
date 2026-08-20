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


class DellServerSiteReviewViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site_a = Site.objects.create(name="Review A", slug="review-a")
        cls.site_b = Site.objects.create(name="Review B", slug="review-b")
        role = DeviceRole.objects.create(name="Srv", slug="srv-review")
        mfr = Manufacturer.objects.create(name="Dell", slug="dell-review")
        dtype = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450-review"
        )
        cls.pending = [
            DellServer.objects.create(
                device=Device.objects.create(
                    name=f"pending-{i}", site=cls.site_a, role=role,
                    device_type=dtype,
                ),
                idrac_address=f"10.70.0.{i}",
                site_confirmed=False,
            )
            for i in (1, 2)
        ]
        cls.confirmed = DellServer.objects.create(
            device=Device.objects.create(
                name="confirmed-1", site=cls.site_a, role=role,
                device_type=dtype,
            ),
            idrac_address="10.70.0.9",
            site_confirmed=True,
        )
        cls.user = get_user_model().objects.create_superuser(
            username="review-admin"
        )

    def _management_data(self, count):
        return {
            "form-TOTAL_FORMS": str(count),
            "form-INITIAL_FORMS": str(count),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }

    def test_get_lists_only_unconfirmed_servers(self):
        self.client.force_login(self.user)
        url = reverse("plugins:netbox_idrac_inventory:dellserver_site_review")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("10.70.0.1", content)
        self.assertIn("10.70.0.2", content)
        self.assertNotIn("10.70.0.9", content)

    def test_post_updates_site_and_confirms(self):
        self.client.force_login(self.user)
        url = reverse("plugins:netbox_idrac_inventory:dellserver_site_review")
        data = self._management_data(2)
        for i, server in enumerate(self.pending):
            data[f"form-{i}-server_id"] = str(server.pk)
            data[f"form-{i}-site"] = str(self.site_b.pk)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        for server in self.pending:
            server.refresh_from_db()
            server.device.refresh_from_db()
            self.assertTrue(server.site_confirmed)
            self.assertEqual(server.device.site, self.site_b)

    def test_post_blank_row_stays_pending(self):
        self.client.force_login(self.user)
        url = reverse("plugins:netbox_idrac_inventory:dellserver_site_review")
        data = self._management_data(2)
        data["form-0-server_id"] = str(self.pending[0].pk)
        data["form-0-site"] = str(self.site_b.pk)
        data["form-1-server_id"] = str(self.pending[1].pk)
        data["form-1-site"] = ""
        self.client.post(url, data)
        self.pending[0].refresh_from_db()
        self.pending[1].refresh_from_db()
        self.assertTrue(self.pending[0].site_confirmed)
        self.assertFalse(self.pending[1].site_confirmed)
