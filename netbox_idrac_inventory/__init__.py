from netbox.plugins import PluginConfig

__version__ = "0.2.0"


class DellInventoryConfig(PluginConfig):
    name = "netbox_idrac_inventory"
    verbose_name = "NetBox iDRAC Inventory"
    description = "Synchronize Dell servers with NetBox via the iDRAC Redfish API."
    version = __version__
    author = "Thomas Le Gentil"
    base_url = "idrac-inventory"
    min_version = "4.1.0"
    # NetBox compares the full version ("4.6" would reject 4.6.4), so use
    # .99 to admit every 4.6.x patch release.
    max_version = "4.6.99"

    # Global plugin settings. Per-device values (when set) take precedence.
    # Credentials are intentionally NOT stored in the database by default:
    # the iDRAC password is resolved at sync time from these settings (or
    # environment) so it never lands in NetBox's DB in plaintext.
    default_settings = {
        "idrac_default_username": "root",
        "idrac_default_password": "",  # prefer setting via PLUGINS_CONFIG / env
        "idrac_verify_ssl": False,
        "idrac_timeout": 30,
        # When True, the sync also writes service tag -> Device.serial.
        "update_device_serial": True,
        # When True, the sync creates a mgmt-only "iDRAC" interface with the
        # iDRAC IP and sets it as the device's out-of-band IP.
        "manage_idrac_interface": True,
        # Minutes between automatic syncs of every Dell server. 0 disables the
        # recurring system job (sync stays manual / on-demand only).
        "sync_interval_minutes": 0,
        # Prefixes (e.g. ["10.0.0.0/8"]) that iDRAC addresses / scan targets
        # must fall within. Empty = no restriction. Prevents a user with
        # change permission from pointing a sync (and thus the iDRAC
        # credentials) at an arbitrary host.
        "allowed_networks": [],
    }

    def ready(self):
        super().ready()
        from django.db.models.signals import post_migrate

        from .signals import create_lldp_custom_fields

        # Create the LLDP custom fields after migrations. Done via post_migrate
        # (idempotent get_or_create) rather than a data migration so it stays
        # robust across NetBox versions instead of pinning a core migration.
        post_migrate.connect(create_lldp_custom_fields, sender=self)

        # Import jobs so the recurring system job registers itself (NetBox
        # does not auto-import a plugin's jobs module). The rqworker schedules
        # registered system jobs at startup.
        from . import jobs  # noqa: F401


config = DellInventoryConfig
