"""REST API serializers for netbox_idrac_inventory.

The per-device/per-range ``idrac_password`` is write-only: it is encrypted
before it reaches the model and is never included in a response. Sending a
blank/absent password keeps the stored value (it cannot be cleared via the
API; use the UI form for that).
"""

from dcim.api.serializers import DeviceSerializer
from netbox.api.serializers import NetBoxModelSerializer
from rest_framework import serializers

from netbox_idrac_inventory.models import (
    DellComponent,
    DellScanRange,
    DellServer,
)
from netbox_idrac_inventory.utils import encrypt_secret


class EncryptedPasswordSerializerMixin(serializers.Serializer):
    """Adds a write-only ``idrac_password`` field, encrypted at rest."""

    idrac_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"},
        help_text=(
            "Per-object iDRAC password, stored encrypted; never returned. "
            "Blank or absent keeps the current value."
        ),
    )

    def validate(self, data):
        # Strip/encrypt before super(): NetBox's ValidatedModelSerializer
        # copies attrs onto the instance during validation, so a blank
        # password left in *data* would overwrite the stored secret.
        password = data.pop("idrac_password", None)
        if password:
            data["idrac_password"] = encrypt_secret(password)
        return super().validate(data)


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


class DellServerSerializer(EncryptedPasswordSerializerMixin, NetBoxModelSerializer):
    """Serializer for a Dell server record linked to a NetBox Device.

    Includes:
      - device: nested brief DeviceSerializer.
      - component_count: read-only; uses the viewset's annotation when
        present and falls back to a count query (e.g. right after create).
    """

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:netbox_idrac_inventory-api:dellserver-detail",
    )

    device = DeviceSerializer(nested=True)

    component_count = serializers.SerializerMethodField()

    class Meta:
        model = DellServer
        fields = (
            "id",
            "url",
            "display",
            "device",
            "idrac_address",
            "idrac_username",
            "idrac_password",
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

    def get_component_count(self, obj) -> int:
        count = getattr(obj, "component_count", None)
        return obj.components.count() if count is None else count


class DellScanRangeSerializer(EncryptedPasswordSerializerMixin, NetBoxModelSerializer):
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
            "idrac_password",
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
