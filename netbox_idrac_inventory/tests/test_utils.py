# Tests for the address helpers and the encryption fail-closed behaviour.
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from netbox_idrac_inventory.utils import (
    SecretDecryptionError,
    check_address_allowed,
    decrypt_secret,
    default_device_name,
    detect_idrac_address,
    encrypt_secret,
    host_part,
)


class HostPartTest(SimpleTestCase):
    def test_plain_host(self):
        self.assertEqual(host_part("idrac01.example.com"), "idrac01.example.com")

    def test_host_with_port(self):
        self.assertEqual(host_part("idrac01.example.com:443"), "idrac01.example.com")

    def test_ipv6_kept_whole(self):
        self.assertEqual(host_part("2001:db8::10"), "2001:db8::10")

    def test_bracketed_ipv6_with_port(self):
        self.assertEqual(host_part("[2001:db8::10]:443"), "2001:db8::10")


class DefaultDeviceNameIPv6Test(SimpleTestCase):
    def test_ipv6_is_kept_whole(self):
        self.assertEqual(default_device_name("2001:db8::10"), "2001:db8::10")

    def test_bracketed_ipv6_with_port_is_kept_whole(self):
        self.assertEqual(default_device_name("[2001:db8::10]:443"), "2001:db8::10")


class CheckAddressAllowedTest(SimpleTestCase):
    NETWORKS = ["10.0.0.0/8", "2001:db8::/32"]

    def test_empty_networks_allows_everything(self):
        check_address_allowed("192.168.1.1", [])  # no raise

    def test_ip_inside_prefix(self):
        check_address_allowed("10.20.30.40", self.NETWORKS)
        check_address_allowed("2001:db8::10", self.NETWORKS)

    def test_ip_outside_prefix_raises(self):
        with self.assertRaises(ValueError):
            check_address_allowed("192.168.1.1", self.NETWORKS)

    def test_hostname_is_resolved(self):
        with patch(
            "netbox_idrac_inventory.utils.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.5.5.5", 0))],
        ):
            check_address_allowed("idrac01.example.com", self.NETWORKS)
        with patch(
            "netbox_idrac_inventory.utils.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.1", 0))],
        ):
            with self.assertRaises(ValueError):
                check_address_allowed("evil.example.com", self.NETWORKS)

    def test_unresolvable_hostname_raises(self):
        with patch(
            "netbox_idrac_inventory.utils.socket.getaddrinfo",
            side_effect=OSError("no such host"),
        ):
            with self.assertRaises(ValueError):
                check_address_allowed("nowhere.example.com", self.NETWORKS)


class DetectIdracAddressTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from dcim.models import DeviceRole, DeviceType, Manufacturer, Site

        cls.site = Site.objects.create(name="Detect", slug="detect")
        cls.role = DeviceRole.objects.create(name="Srv", slug="srv-detect")
        mfr = Manufacturer.objects.create(name="Dell", slug="dell-detect")
        cls.dtype = DeviceType.objects.create(
            manufacturer=mfr, model="R450", slug="r450-detect"
        )

    def _device(self, name):
        from dcim.models import Device

        return Device.objects.create(
            name=name, site=self.site, role=self.role, device_type=self.dtype
        )

    def test_no_idrac_interface_returns_empty(self):
        device = self._device("no-idrac")
        self.assertEqual(detect_idrac_address(device), "")

    def test_idrac_interface_without_ip_returns_empty(self):
        from dcim.models import Interface

        device = self._device("idrac-no-ip")
        Interface.objects.create(device=device, name="iDRAC", type="1000base-t")
        self.assertEqual(detect_idrac_address(device), "")

    def test_idrac_interface_with_ip_is_detected(self):
        from dcim.models import Interface
        from django.contrib.contenttypes.models import ContentType
        from ipam.models import IPAddress

        device = self._device("idrac-with-ip")
        # Case-insensitive name match — pre-existing setups may differ in case.
        iface = Interface.objects.create(
            device=device, name="idrac", type="1000base-t"
        )
        IPAddress.objects.create(
            address="10.20.30.40/24",
            assigned_object_type=ContentType.objects.get_for_model(Interface),
            assigned_object_id=iface.pk,
        )
        self.assertEqual(detect_idrac_address(device), "10.20.30.40")


class SecretRotationTest(SimpleTestCase):
    ROTATED = "rotated-secret-key-0123456789abcdefghijklmnopqrstuvwxyz"

    def test_decrypt_fails_closed_after_key_rotation(self):
        token = encrypt_secret("s3cret")
        with override_settings(SECRET_KEY=self.ROTATED):
            with self.assertRaises(SecretDecryptionError):
                decrypt_secret(token)

    def test_decrypt_uses_secret_key_fallbacks(self):
        original = settings.SECRET_KEY
        token = encrypt_secret("s3cret")
        with override_settings(
            SECRET_KEY=self.ROTATED, SECRET_KEY_FALLBACKS=[original]
        ):
            self.assertEqual(decrypt_secret(token), "s3cret")

    def test_garbage_token_raises(self):
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret("not-a-fernet-token")
