# REST API serializers for netbox_idrac_inventory.
#
# Conventions confirmed from NetBox 4.x plugin docs
# (https://netboxlabs.com/docs/netbox/en/stable/plugins/development/rest-api/):
#   - Subclass NetBoxModelSerializer for all plugin model serializers.
#   - Nested (brief) representation is controlled by Meta.brief_fields.
#   - Related objects use their own serializer with nested=True for brief inline
#     representation; this is the standard NetBox 4.x pattern (not extra_kwargs).
#   - HyperlinkedIdentityField view_name for plugin objects follows the pattern
#     "plugins-api:<app_label>-api:<model>-detail".

from rest_framework import serializers
from netbox.api.serializers import NetBoxModelSerializer

# Lazy import to avoid circular issues at module load time; these are resolved
# once the Django app registry is ready.
from dcim.api.serializers import DeviceSerializer

from netbox_idrac_inventory.models import (
    DellComponent,
    DellScanRange,
    DellServer,
)


class DellComponentSerializer(NetBoxModelSerializer):
    """Serializer for individual hardware components discovered on a Dell server."""

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_idrac_inventory-api:dellcomponent-detail",
    )

    class Meta:
        model = DellComponent
        fields = (
            "id",
            "url",
            "display",
            "server",
            "component_type",
            "name",
            "manufacturer",
            "model",
            "serial",
            "part_number",
            "firmware",
            "capacity_bytes",
            "health",
            "data",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = (
            "id",
            "url",
            "display",
            "component_type",
            "name",
        )


class DellServerSerializer(NetBoxModelSerializer):
    """Serializer for a Dell server record linked to a NetBox Device.

    Includes:
      - device: nested brief DeviceSerializer (nested=True is the NetBox 4.x
        convention for inline related-object representations).
      - component_count: read-only count sourced from the reverse relation.
    """

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_idrac_inventory-api:dellserver-detail",
    )

    # nested=True requests the brief (brief_fields) representation of the device.
    # This is the documented NetBox 4.x pattern for related-object nesting.
    device = DeviceSerializer(nested=True)

    component_count = serializers.IntegerField(
        source="components.count",
        read_only=True,
    )

    class Meta:
        model = DellServer
        fields = (
            "id",
            "url",
            "display",
            "device",
            "idrac_address",
            "idrac_username",
            "service_tag",
            "model",
            "bios_version",
            "idrac_firmware",
            "health",
            "sync_status",
            "last_synced",
            "sync_message",
            "comments",
            "component_count",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = (
            "id",
            "url",
            "display",
            "service_tag",
            "model",
            "sync_status",
        )


class DellScanRangeSerializer(NetBoxModelSerializer):
    """Serializer for a Dell discovery scan range."""

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_idrac_inventory-api:dellscanrange-detail",
    )

    class Meta:
        model = DellScanRange
        fields = (
            "id",
            "url",
            "display",
            "name",
            "targets",
            "idrac_username",
            "site",
            "role",
            "enabled",
            "last_run",
            "message",
            "comments",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "enabled")
