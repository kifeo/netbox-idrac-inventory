import django_tables2 as tables

from netbox.tables import NetBoxTable
from netbox.tables.columns import ChoiceFieldColumn

from .models import DellComponent, DellScanRange, DellServer


class DellServerTable(NetBoxTable):
    """Table for listing DellServer instances."""

    # device column: linkify to the Device detail page
    device = tables.Column(linkify=True)
    # sync_status / health rendered as colored badges via ChoiceFieldColumn
    sync_status = ChoiceFieldColumn()
    health = ChoiceFieldColumn()
    # Pre-annotated component count (queryset must annotate as "component_count")
    component_count = tables.Column(
        verbose_name="Components",
        orderable=False,
    )

    class Meta(NetBoxTable.Meta):
        model = DellServer
        fields = (
            "pk",
            "id",
            "device",
            "idrac_address",
            "service_tag",
            "model",
            "health",
            "sync_status",
            "last_synced",
            "component_count",
            "actions",
        )
        default_columns = (
            "pk",
            "device",
            "idrac_address",
            "service_tag",
            "model",
            "health",
            "sync_status",
            "last_synced",
            "component_count",
            "actions",
        )


class DellComponentTable(NetBoxTable):
    """Table for listing DellComponent instances."""

    # server column: linkify to the DellServer detail page
    server = tables.Column(linkify=True)
    # component_type / health rendered as colored badges
    component_type = ChoiceFieldColumn()
    health = ChoiceFieldColumn()

    class Meta(NetBoxTable.Meta):
        model = DellComponent
        fields = (
            "pk",
            "id",
            "server",
            "component_type",
            "name",
            "manufacturer",
            "model",
            "serial",
            "capacity_bytes",
            "health",
            "actions",
        )
        default_columns = (
            "pk",
            "server",
            "component_type",
            "name",
            "manufacturer",
            "model",
            "health",
            "actions",
        )


class DellScanRangeTable(NetBoxTable):
    """Table for listing DellScanRange instances."""

    name = tables.Column(linkify=True)
    enabled = tables.BooleanColumn()
    site = tables.Column(linkify=True)

    class Meta(NetBoxTable.Meta):
        model = DellScanRange
        fields = (
            "pk",
            "id",
            "name",
            "targets",
            "site",
            "role",
            "enabled",
            "last_run",
            "actions",
        )
        default_columns = (
            "pk",
            "name",
            "targets",
            "site",
            "role",
            "enabled",
            "last_run",
            "actions",
        )
