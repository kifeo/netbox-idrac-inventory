# REST API tests for netbox_idrac_inventory.
#
# Uses NetBox's built-in APIViewTestCases which provide generic test methods for
# each HTTP verb.  Confirmed from NetBox source (utilities/testing/api.py):
#
#   APIViewTestCases contains inner classes:
#     - GetObjectViewTestCase
#     - ListObjectsViewTestCase  (needs brief_fields)
#     - CreateObjectViewTestCase (needs create_data)
#     - UpdateObjectViewTestCase (needs update_data / bulk_update_data)
#     - DeleteObjectViewTestCase
#
#   Required class attributes on the test class:
#     model              – the Django model class under test
#     view_namespace     – optional; namespace prefix for URL reversal
#                          (defaults to "plugins-api:<app_label>")
#     brief_fields       – list of field names expected in ?brief=true responses
#     create_data        – list[dict] of payloads for POST (min 3 items for bulk)
#     bulk_update_data   – dict applied to all objects in a bulk PATCH
#
#   The mixin also provides a setUp() that creates a token-authenticated API
#   client.  Subclasses only need to populate DB fixtures in setUp() and call
#   super().setUp().

from unittest.mock import MagicMock, patch

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site
from django.test import TestCase
from django.urls import reverse
from utilities.testing import APITestCase, APIViewTestCases

from netbox_idrac_inventory.choices import ComponentTypeChoices
from netbox_idrac_inventory.models import DellComponent, DellServer

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _get_or_create_site():
    return Site.objects.get_or_create(name="API Test Site", slug="api-test-site")[0]


def _get_or_create_device_type():
    mfr, _ = Manufacturer.objects.get_or_create(name="Dell Inc.", slug="dell-inc")
    return DeviceType.objects.get_or_create(
        manufacturer=mfr, model="PowerEdge R740xd", slug="poweredge-r740xd"
    )[0]


def _get_or_create_role():
    return DeviceRole.objects.get_or_create(name="API Server", slug="api-server")[0]


def _make_device(name: str) -> Device:
    return Device.objects.create(
        name=name,
        site=_get_or_create_site(),
        device_type=_get_or_create_device_type(),
        role=_get_or_create_role(),
    )


# ---------------------------------------------------------------------------
# DellServer API tests
# ---------------------------------------------------------------------------

class DellServerAPITestCase(
    APIViewTestCases.GetObjectViewTestCase,
    APIViewTestCases.ListObjectsViewTestCase,
    APIViewTestCases.CreateObjectViewTestCase,
    APIViewTestCases.UpdateObjectViewTestCase,
    APIViewTestCases.DeleteObjectViewTestCase,
    TestCase,
):
    """Tests for the DellServer REST API endpoints."""

    model = DellServer
    # APIViewTestCases builds the viewname as "{view_namespace}-api:...".
    # For a plugin the namespace must include the "plugins-api:" prefix.
    view_namespace = "plugins-api:netbox_idrac_inventory"

    # Fields expected in a brief (?brief=true) list response.
    # These must match DellServerSerializer.Meta.brief_fields.
    # Must be sorted: the test compares sorted(response keys) == brief_fields.
    brief_fields = ["display", "id", "model", "service_tag", "sync_status", "url"]

    # Bulk PATCH payload — fields that can be updated on all selected objects.
    bulk_update_data = {
        "idrac_username": "admin-bulk",
        "comments": "bulk-updated",
    }

    def setUp(self):
        super().setUp()

        # Create three pre-existing servers so list/update/delete tests have objects.
        for i in range(1, 4):
            device = _make_device(f"api-server-{i:02d}")
            DellServer.objects.create(
                device=device,
                idrac_address=f"10.100.{i}.1",
                service_tag=f"SVC{i:04d}",
            )

        # create_data: three payloads for the CreateObjectViewTestCase.
        # Device IDs are referenced by PK; we create fresh devices here.
        dev_a = _make_device("api-new-a")
        dev_b = _make_device("api-new-b")
        dev_c = _make_device("api-new-c")

        self.create_data = [
            {
                "device": dev_a.pk,
                "idrac_address": "10.200.1.1",
                "service_tag": "NEWAAA1",
            },
            {
                "device": dev_b.pk,
                "idrac_address": "10.200.1.2",
                "service_tag": "NEWBBB1",
            },
            {
                "device": dev_c.pk,
                "idrac_address": "10.200.1.3",
                "service_tag": "NEWCCC1",
            },
        ]


# ---------------------------------------------------------------------------
# DellComponent API tests
# ---------------------------------------------------------------------------

class DellComponentAPITestCase(
    APIViewTestCases.GetObjectViewTestCase,
    APIViewTestCases.ListObjectsViewTestCase,
    APIViewTestCases.CreateObjectViewTestCase,
    APIViewTestCases.UpdateObjectViewTestCase,
    APIViewTestCases.DeleteObjectViewTestCase,
    TestCase,
):
    """Tests for the DellComponent REST API endpoints."""

    model = DellComponent
    view_namespace = "plugins-api:netbox_idrac_inventory"

    # Fields expected in a brief (?brief=true) list response.
    # These must match DellComponentSerializer.Meta.brief_fields.
    # Must be sorted: the test compares sorted(response keys) == brief_fields.
    brief_fields = ["component_type", "display", "id", "name", "url"]

    bulk_update_data = {
        "manufacturer": "Updated Manufacturer",
    }

    def setUp(self):
        super().setUp()

        # Shared server for all pre-existing fixture components.
        device = _make_device("comp-api-server-01")
        self.server = DellServer.objects.create(
            device=device,
            idrac_address="10.150.1.1",
        )

        # Create three pre-existing components.
        for i in range(1, 4):
            DellComponent.objects.create(
                server=self.server,
                component_type=ComponentTypeChoices.TYPE_CPU,
                name=f"CPU.Socket.{i}",
            )

        # create_data payloads — using unique names to avoid unique constraint issues.
        self.create_data = [
            {
                "server": self.server.pk,
                "component_type": ComponentTypeChoices.TYPE_MEMORY,
                "name": "DIMM.Slot.A1",
                "manufacturer": "Samsung",
            },
            {
                "server": self.server.pk,
                "component_type": ComponentTypeChoices.TYPE_DISK,
                "name": "Disk.Bay.0:Enclosure.Internal.0-1",
                "capacity_bytes": 480_000_000_000,
            },
            {
                "server": self.server.pk,
                "component_type": ComponentTypeChoices.TYPE_NIC,
                "name": "NIC.Slot.1-1",
                "manufacturer": "Broadcom",
            },
        ]


# ---------------------------------------------------------------------------
# Password handling and custom actions
# ---------------------------------------------------------------------------

class DellServerPasswordAPITestCase(APITestCase):
    """The per-device password is write-only and encrypted at rest."""

    def test_password_is_encrypted_and_never_returned(self):
        from netbox_idrac_inventory.utils import decrypt_secret

        self.add_permissions("netbox_idrac_inventory.add_dellserver")
        device = _make_device("pw-api-01")
        url = reverse(
            "plugins-api:netbox_idrac_inventory-api:dellserver-list"
        )
        response = self.client.post(
            url,
            {
                "device": device.pk,
                "idrac_address": "10.99.0.1",
                "idrac_password": "apisecret",
            },
            format="json",
            **self.header,
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("idrac_password", response.data)

        server = DellServer.objects.get(idrac_address="10.99.0.1")
        self.assertTrue(server.idrac_password)
        self.assertNotIn("apisecret", server.idrac_password)
        self.assertEqual(decrypt_secret(server.idrac_password), "apisecret")

    def test_blank_password_keeps_stored_value(self):
        from netbox_idrac_inventory.utils import encrypt_secret

        self.add_permissions("netbox_idrac_inventory.change_dellserver")
        device = _make_device("pw-api-02")
        server = DellServer.objects.create(
            device=device,
            idrac_address="10.99.0.2",
            idrac_password=encrypt_secret("keepme"),
        )
        stored = server.idrac_password

        url = reverse(
            "plugins-api:netbox_idrac_inventory-api:dellserver-detail",
            kwargs={"pk": server.pk},
        )
        response = self.client.patch(
            url,
            {"idrac_password": "", "comments": "patched"},
            format="json",
            **self.header,
        )
        self.assertEqual(response.status_code, 200, response.data)
        server.refresh_from_db()
        self.assertEqual(server.idrac_password, stored)


class DellServerSyncActionAPITestCase(APITestCase):
    """The sync action needs change permission and returns a core job URL."""

    def _post_sync(self, server):
        url = reverse(
            "plugins-api:netbox_idrac_inventory-api:dellserver-sync",
            kwargs={"pk": server.pk},
        )
        return self.client.post(url, {}, format="json", **self.header)

    def test_sync_rejected_without_change_permission(self):
        # add satisfies NetBox's built-in POST mapping, but the action
        # itself must still require change.
        self.add_permissions("netbox_idrac_inventory.add_dellserver")
        server = DellServer.objects.create(
            device=_make_device("sync-api-01"), idrac_address="10.99.1.1"
        )
        response = self._post_sync(server)
        self.assertEqual(response.status_code, 403)

    def test_sync_enqueues_job(self):
        self.add_permissions(
            "netbox_idrac_inventory.add_dellserver",
            "netbox_idrac_inventory.change_dellserver",
        )
        server = DellServer.objects.create(
            device=_make_device("sync-api-02"), idrac_address="10.99.1.2"
        )
        with patch(
            "netbox_idrac_inventory.api.views.enqueue_sync",
            return_value=MagicMock(pk=123),
        ) as mock_enqueue:
            response = self._post_sync(server)
        self.assertEqual(response.status_code, 202, response.data)
        mock_enqueue.assert_called_once()
        self.assertEqual(response.data["job_id"], 123)
        self.assertIn("/api/core/jobs/123/", response.data["job_url"])
