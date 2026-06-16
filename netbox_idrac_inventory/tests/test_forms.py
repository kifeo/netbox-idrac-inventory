# Tests for the device-creating DellServerForm and the name helper.
from django.test import TestCase

from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site

from netbox_idrac_inventory.forms import DellServerForm
from netbox_idrac_inventory.utils import default_device_name


class DefaultDeviceNameTest(TestCase):
    def test_fqdn_returns_host_label(self):
        self.assertEqual(
            default_device_name("idrac01.example.com"), "idrac01"
        )

    def test_ipv4_is_kept_whole(self):
        self.assertEqual(default_device_name("10.0.0.5"), "10.0.0.5")

    def test_port_suffix_is_dropped(self):
        self.assertEqual(default_device_name("host.example.com:443"), "host")

    def test_empty(self):
        self.assertEqual(default_device_name(""), "")


class DellServerFormTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="S1", slug="s1")
        cls.role = DeviceRole.objects.create(name="Srv", slug="srv")

    def test_creates_device_named_from_fqdn(self):
        form = DellServerForm(data={
            "idrac_address": "node12.ipmi.example.com",
            "site": self.site.pk,
            "role": self.role.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        server = form.save()
        self.assertEqual(server.device.name, "node12")
        self.assertEqual(server.device.site, self.site)
        self.assertEqual(server.device.role, self.role)

    def test_explicit_name_overrides_default(self):
        form = DellServerForm(data={
            "idrac_address": "node13.ipmi.example.com",
            "name": "custom-name",
            "site": self.site.pk,
            "role": self.role.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().device.name, "custom-name")

    def test_requires_site_and_role_to_create(self):
        form = DellServerForm(data={"idrac_address": "node14.x.y"})
        self.assertFalse(form.is_valid())
        self.assertIn("site", form.errors)
        self.assertIn("role", form.errors)

    def test_links_existing_device_without_creating(self):
        mfr = Manufacturer.objects.create(name="Dell", slug="dell")
        dt = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450")
        device = Device.objects.create(
            name="preexisting", site=self.site, role=self.role,
            device_type=dt)
        before = Device.objects.count()
        form = DellServerForm(data={
            "idrac_address": "node15.ipmi.example.com",
            "device": device.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        server = form.save()
        self.assertEqual(server.device, device)
        # No new device created, and the existing name is left untouched.
        self.assertEqual(Device.objects.count(), before)
        device.refresh_from_db()
        self.assertEqual(device.name, "preexisting")


class EncryptedPasswordTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="Pw", slug="pw")
        cls.role = DeviceRole.objects.create(name="Pwr", slug="pwr")

    def test_encrypt_roundtrip(self):
        from netbox_idrac_inventory.utils import decrypt_secret, encrypt_secret

        token = encrypt_secret("s3cret")
        self.assertNotIn("s3cret", token)
        self.assertEqual(decrypt_secret(token), "s3cret")
        self.assertEqual(encrypt_secret(""), "")
        self.assertEqual(decrypt_secret(""), "")

    def test_form_stores_encrypted_and_creds_resolve(self):
        from netbox_idrac_inventory.idrac.sync import resolve_credentials
        from netbox_idrac_inventory.models import DellServer

        form = DellServerForm(data={
            "idrac_address": "pw-host.example.com",
            "idrac_username": "svc",
            "idrac_password": "topsecret",
            "site": self.site.pk,
            "role": self.role.pk,
        })
        self.assertTrue(form.is_valid(), form.errors)
        server = form.save()

        # Stored ciphertext, not the plaintext.
        self.assertTrue(server.idrac_password)
        self.assertNotIn("topsecret", server.idrac_password)
        # Per-server password wins and decrypts for the sync client.
        user, pwd = resolve_credentials(server)
        self.assertEqual(user, "svc")
        self.assertEqual(pwd, "topsecret")

        # Editing without re-entering the password keeps the stored value.
        stored = server.idrac_password
        form2 = DellServerForm(data={
            "idrac_address": "pw-host.example.com",
            "idrac_username": "svc",
            "idrac_password": "",
            "site": self.site.pk,
            "role": self.role.pk,
        }, instance=DellServer.objects.get(pk=server.pk))
        self.assertTrue(form2.is_valid(), form2.errors)
        self.assertEqual(form2.save().idrac_password, stored)
