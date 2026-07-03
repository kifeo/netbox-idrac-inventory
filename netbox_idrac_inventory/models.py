"""Database models: DellServer (one per Device) and its DellComponents."""

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from netbox.models import NetBoxModel
from netbox.models.features import JobsMixin

from .choices import ComponentTypeChoices, HealthChoices, SyncStatusChoices


class DellServer(JobsMixin, NetBoxModel):
    """
    iDRAC-managed Dell server, attached one-to-one to a NetBox Device.

    Holds the connection endpoint plus identity attributes reported by iDRAC
    (service tag, model, BIOS version) and the result of the last sync.
    """

    device = models.OneToOneField(
        to="dcim.Device",
        on_delete=models.CASCADE,
        related_name="dell_server",
    )
    idrac_address = models.CharField(
        max_length=255,
        help_text="Hostname or IP of the iDRAC management interface.",
    )
    idrac_username = models.CharField(
        max_length=128,
        blank=True,
        help_text="Overrides the plugin's default iDRAC username when set.",
    )
    idrac_password = models.TextField(
        blank=True,
        help_text=(
            "Per-device iDRAC password, encrypted at rest. Overrides the "
            "plugin default when set. Managed via the form; never returned."
        ),
    )
    service_tag = models.CharField(max_length=64, blank=True)
    model = models.CharField(max_length=128, blank=True)
    bios_version = models.CharField(max_length=64, blank=True)
    idrac_firmware = models.CharField(max_length=64, blank=True)

    health = models.CharField(
        max_length=20,
        choices=HealthChoices,
        default=HealthChoices.HEALTH_UNKNOWN,
        blank=True,
        help_text="Overall hardware health rolled up from iDRAC.",
    )

    sync_status = models.CharField(
        max_length=30,
        choices=SyncStatusChoices,
        default=SyncStatusChoices.STATUS_NEW,
    )
    last_synced = models.DateTimeField(blank=True, null=True)
    sync_message = models.TextField(
        blank=True,
        help_text="Detail of the last sync result (error message on failure).",
    )

    comments = models.TextField(blank=True)

    class Meta:
        ordering = ("device",)
        verbose_name = "Dell server"
        verbose_name_plural = "Dell servers"

    def __str__(self):
        return f"{self.device} ({self.service_tag or self.idrac_address})"

    def get_absolute_url(self):
        return reverse("plugins:netbox_idrac_inventory:dellserver", args=[self.pk])

    def get_sync_status_color(self):
        return SyncStatusChoices.colors.get(self.sync_status)

    def get_health_color(self):
        return HealthChoices.colors.get(self.health)


class DellScanRange(JobsMixin, NetBoxModel):
    """
    A set of iDRAC targets (CIDRs / ranges / single IPs) to probe and import.

    Running a scan connects to each reachable iDRAC, and either attaches to an
    existing Device matching the service tag or creates a new one, then syncs.
    Created devices use this range's site and role.
    """

    name = models.CharField(max_length=128, unique=True)
    targets = models.TextField(
        help_text=(
            "iDRAC targets, one per line or comma-separated: a CIDR "
            "(10.0.0.0/24), a range (10.0.0.10-20) or a single host."
        ),
    )
    idrac_username = models.CharField(
        max_length=128,
        blank=True,
        help_text="iDRAC username for discovered hosts (else plugin default).",
    )
    idrac_password = models.TextField(
        blank=True,
        help_text=(
            "iDRAC password for discovered hosts, encrypted at rest. "
            "Overrides the plugin default when set."
        ),
    )
    site = models.ForeignKey(
        to="dcim.Site",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Site assigned to devices created by this scan.",
    )
    role = models.ForeignKey(
        to="dcim.DeviceRole",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Role assigned to devices created by this scan.",
    )
    enabled = models.BooleanField(default=True)

    last_run = models.DateTimeField(blank=True, null=True)
    message = models.TextField(
        blank=True,
        help_text="Summary of the last scan run.",
    )
    comments = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Dell scan range"
        verbose_name_plural = "Dell scan ranges"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            "plugins:netbox_idrac_inventory:dellscanrange", args=[self.pk]
        )


class DellComponent(NetBoxModel):
    """
    A single hardware component (CPU, DIMM, disk, NIC, PSU…) discovered on a
    DellServer during synchronization. The raw iDRAC payload is preserved in
    `data` so consumers can read attributes not promoted to columns.
    """

    server = models.ForeignKey(
        to=DellServer,
        on_delete=models.CASCADE,
        related_name="components",
    )
    component_type = models.CharField(
        max_length=30,
        choices=ComponentTypeChoices,
    )
    name = models.CharField(
        max_length=255,
        help_text="iDRAC component identifier (e.g. CPU.Socket.1).",
    )
    manufacturer = models.CharField(max_length=128, blank=True)
    model = models.CharField(max_length=255, blank=True)
    serial = models.CharField(max_length=128, blank=True)
    part_number = models.CharField(max_length=128, blank=True)
    firmware = models.CharField(max_length=64, blank=True)
    # Generic size field: bytes for storage/memory, count/MHz left to `data`.
    capacity_bytes = models.BigIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    health = models.CharField(
        max_length=20,
        choices=HealthChoices,
        default=HealthChoices.HEALTH_UNKNOWN,
        blank=True,
        help_text="Component health reported by iDRAC.",
    )
    data = models.JSONField(
        blank=True,
        default=dict,
        help_text="Raw attributes for this component as returned by iDRAC.",
    )

    class Meta:
        ordering = ("server", "component_type", "name")
        verbose_name = "Dell component"
        verbose_name_plural = "Dell components"
        constraints = [
            models.UniqueConstraint(
                fields=["server", "component_type", "name"],
                name="%(app_label)s_%(class)s_unique_per_server",
            ),
        ]

    def __str__(self):
        return f"{self.get_component_type_display()}: {self.name}"

    def get_absolute_url(self):
        return reverse("plugins:netbox_idrac_inventory:dellcomponent", args=[self.pk])

    def get_component_type_color(self):
        return ComponentTypeChoices.colors.get(self.component_type)

    def get_health_color(self):
        return HealthChoices.colors.get(self.health)
