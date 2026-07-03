"""Forms for the netbox_idrac_inventory UI (edit/filter)."""

from dcim.models import Device, DeviceRole, Site
from django import forms
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from utilities.forms.fields import (
    CommentField,
    DynamicModelChoiceField,
)
from utilities.forms.rendering import FieldSet

from .choices import ComponentTypeChoices, SyncStatusChoices
from .models import DellComponent, DellScanRange, DellServer
from .utils import (
    default_device_name,
    encrypt_secret,
    get_or_create_manufacturer,
)

# ---------------------------------------------------------------------------
# DellServer forms
# ---------------------------------------------------------------------------


class DellServerForm(NetBoxModelForm):
    """
    Create / edit form for a DellServer.

    The plugin owns the linked Device: on add, it is created from the fields
    below. ``name`` defaults to the host part of the iDRAC FQDN when left
    blank (e.g. ``idrac01.example.com`` -> ``idrac01``). The device
    type is left as a placeholder and replaced by the iDRAC-reported model on
    the first sync.
    """

    name = forms.CharField(
        required=False,
        label="Device name",
        help_text=(
            "Name for the created device. Defaults to the host part of the "
            "iDRAC FQDN if left blank."
        ),
    )
    site = DynamicModelChoiceField(
        queryset=Site.objects.all(),
        required=False,
        help_text="Site for the created device (required when creating one).",
    )
    role = DynamicModelChoiceField(
        queryset=DeviceRole.objects.all(),
        required=False,
        help_text="Role for the created device (required when creating one).",
    )
    # Plumbing for the "Add Dell server" button on a Device page: attach an
    # existing device instead of creating one. Not shown as a normal selector.
    device = forms.ModelChoiceField(
        queryset=Device.objects.all(),
        required=False,
        widget=forms.HiddenInput,
    )
    idrac_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label="iDRAC password",
        help_text=(
            "Per-device password, stored encrypted. Overrides the plugin "
            "default. Leave blank to keep the current value."
        ),
    )
    comments = CommentField()

    fieldsets = (
        FieldSet("name", "site", "role", name="Device"),
        FieldSet(
            "idrac_address", "idrac_username", "idrac_password",
            name="iDRAC Connection",
        ),
        FieldSet("tags", name="Tags"),
    )

    class Meta:
        model = DellServer
        fields = [
            "idrac_address",
            "idrac_username",
            "comments",
            "tags",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # When editing, pre-fill the device attributes from the linked device.
        device = self._editing_device()
        if device:
            self.fields["name"].initial = device.name
            self.fields["site"].initial = device.site_id
            self.fields["role"].initial = device.role_id

    def _editing_device(self):
        # Accessing a OneToOne on an unsaved instance raises, not returns None.
        try:
            device = self.instance.device
        except Device.DoesNotExist:
            return None
        return device if (device and device.pk) else None

    def clean(self):
        super().clean()
        cleaned = self.cleaned_data
        # Creating a brand-new device requires a site and a role.
        creating = not self._editing_device() and not cleaned.get("device")
        if creating:
            if not cleaned.get("site"):
                self.add_error("site", "Required to create a new device.")
            if not cleaned.get("role"):
                self.add_error("role", "Required to create a new device.")
        return cleaned

    def save(self, commit=True):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            name = default_device_name(self.cleaned_data.get("idrac_address"))

        device = self._editing_device()
        if device:
            # Editing: keep the device, apply any changed attributes.
            device.name = name or device.name
            if self.cleaned_data.get("site"):
                device.site = self.cleaned_data["site"]
            if self.cleaned_data.get("role"):
                device.role = self.cleaned_data["role"]
            device.save()
        elif self.cleaned_data.get("device"):
            # Attach an existing device (Device-page flow); don't rename it.
            self.instance.device = self.cleaned_data["device"]
        else:
            # Create a new device with a placeholder type (set at first sync).
            from dcim.models import DeviceType

            dtype, _ = DeviceType.objects.get_or_create(
                manufacturer=get_or_create_manufacturer("Dell"),
                model="Unknown",
                defaults={"slug": "dell-unknown"},
            )
            self.instance.device = Device.objects.create(
                name=name,
                site=self.cleaned_data["site"],
                role=self.cleaned_data["role"],
                device_type=dtype,
            )
        # Encrypt a freshly-entered password; blank keeps the stored value.
        password = self.cleaned_data.get("idrac_password")
        if password:
            self.instance.idrac_password = encrypt_secret(password)
        return super().save(commit=commit)


class DellServerFilterForm(NetBoxModelFilterSetForm):
    """Filter form rendered at the top of the DellServer list view.

    Note: NetBoxModelFilterSetForm uses the class-level `model` attribute to
    look up custom fields. We keep `model = DellServer` and use a separate
    `model_search` field to avoid shadowing that attribute. The filterset
    exposes both 'model' and 'model_search' aliases so either works.
    """

    model = DellServer

    sync_status = forms.MultipleChoiceField(
        choices=SyncStatusChoices,
        required=False,
        label="Sync status",
        widget=forms.SelectMultiple(attrs={"size": 4}),
    )
    # 'model_search' maps to the DellServerFilterSet 'model' filter via
    # the filterset alias added there.
    model_search = forms.CharField(
        required=False,
        label="Model",
    )

    fieldsets = (
        FieldSet("q", "sync_status", "model_search", name="Search"),
    )


# ---------------------------------------------------------------------------
# DellComponent forms
# ---------------------------------------------------------------------------


class DellComponentForm(NetBoxModelForm):
    """Create / edit form for a DellComponent."""

    server = DynamicModelChoiceField(
        queryset=DellServer.objects.all(),
        selector=True,
    )

    fieldsets = (
        FieldSet(
            "server",
            "component_type",
            "name",
            name="Identity",
        ),
        FieldSet(
            "manufacturer",
            "model",
            "serial",
            "part_number",
            "firmware",
            "capacity_bytes",
            name="Hardware details",
        ),
        FieldSet("tags", name="Tags"),
    )

    class Meta:
        model = DellComponent
        fields = [
            "server",
            "component_type",
            "name",
            "manufacturer",
            "model",
            "serial",
            "part_number",
            "firmware",
            "capacity_bytes",
            "tags",
        ]


class DellComponentFilterForm(NetBoxModelFilterSetForm):
    """Filter form rendered at the top of the DellComponent list view."""

    model = DellComponent

    component_type = forms.MultipleChoiceField(
        choices=ComponentTypeChoices,
        required=False,
        label="Component type",
        widget=forms.SelectMultiple(attrs={"size": 4}),
    )
    manufacturer = forms.CharField(
        required=False,
        label="Manufacturer",
    )
    server_id = DynamicModelChoiceField(
        queryset=DellServer.objects.all(),
        required=False,
        label="Server",
        selector=True,
    )

    fieldsets = (
        FieldSet("q", "component_type", "manufacturer", "server_id", name="Search"),
    )

    class Meta:
        model = DellComponent
        fields = []


# ---------------------------------------------------------------------------
# DellScanRange forms
# ---------------------------------------------------------------------------


class DellScanRangeForm(NetBoxModelForm):
    """Create / edit form for a scan range."""

    site = DynamicModelChoiceField(queryset=Site.objects.all())
    role = DynamicModelChoiceField(queryset=DeviceRole.objects.all())
    idrac_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label="iDRAC password",
        help_text=(
            "Password for discovered hosts, stored encrypted. Overrides the "
            "plugin default. Leave blank to keep the current value."
        ),
    )
    comments = CommentField()

    fieldsets = (
        FieldSet("name", "targets", "enabled", name="Scan"),
        FieldSet("idrac_username", "idrac_password", name="iDRAC"),
        FieldSet("site", "role", name="Devices created by this scan"),
        FieldSet("tags", name="Tags"),
    )

    def save(self, commit=True):
        password = self.cleaned_data.get("idrac_password")
        if password:
            self.instance.idrac_password = encrypt_secret(password)
        return super().save(commit=commit)

    class Meta:
        model = DellScanRange
        fields = [
            "name",
            "targets",
            "idrac_username",
            "site",
            "role",
            "enabled",
            "comments",
            "tags",
        ]


class DellScanRangeFilterForm(NetBoxModelFilterSetForm):
    """Filter form for the scan-range list."""

    model = DellScanRange

    enabled = forms.NullBooleanField(required=False)

    fieldsets = (FieldSet("q", "enabled", name="Search"),)
