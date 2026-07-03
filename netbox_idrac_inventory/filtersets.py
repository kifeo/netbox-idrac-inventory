"""FilterSets for the netbox_idrac_inventory plugin."""

import django_filters
from django.db.models import Q
from netbox.filtersets import NetBoxModelFilterSet

from .choices import ComponentTypeChoices, SyncStatusChoices
from .models import DellComponent, DellScanRange, DellServer


class DellServerFilterSet(NetBoxModelFilterSet):
    """FilterSet for DellServer.

    Exposes quick search (q) across idrac_address, service_tag and model,
    plus discrete filters for sync_status and model.
    """

    sync_status = django_filters.MultipleChoiceFilter(
        choices=SyncStatusChoices,
    )
    model = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Model (contains)",
    )
    # Alias used by the filter form to avoid shadowing the class-level
    # 'model' attribute on NetBoxModelFilterSetForm subclasses.
    model_search = django_filters.CharFilter(
        field_name="model",
        lookup_expr="icontains",
        label="Model (contains)",
    )

    class Meta:
        """Django-filters Meta: bind filterset to DellServer."""

        model = DellServer
        fields = ["sync_status", "model"]

    def search(self, queryset, _name, value):
        """Full-text search across key text fields (called for the 'q' filter)."""
        return queryset.filter(
            Q(idrac_address__icontains=value)
            | Q(service_tag__icontains=value)
            | Q(model__icontains=value)
        )


class DellComponentFilterSet(NetBoxModelFilterSet):
    """FilterSet for DellComponent.

    Exposes quick search (q) across name, serial, model and manufacturer,
    plus discrete filters for component_type, server and manufacturer.
    """

    component_type = django_filters.MultipleChoiceFilter(
        choices=ComponentTypeChoices,
    )
    manufacturer = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Manufacturer (contains)",
    )
    # Filter by server foreign key — accepts pk values from the form
    server_id = django_filters.ModelMultipleChoiceFilter(
        field_name="server",
        queryset=DellServer.objects.all(),
        label="Server",
    )
    server = django_filters.ModelMultipleChoiceFilter(
        field_name="server",
        queryset=DellServer.objects.all(),
        label="Server",
    )

    class Meta:
        """Django-filters Meta: bind filterset to DellComponent."""

        model = DellComponent
        fields = ["component_type", "manufacturer"]

    def search(self, queryset, _name, value):
        """Full-text search across key text fields (called for the 'q' filter)."""
        return queryset.filter(
            Q(name__icontains=value)
            | Q(serial__icontains=value)
            | Q(model__icontains=value)
            | Q(manufacturer__icontains=value)
        )


class DellScanRangeFilterSet(NetBoxModelFilterSet):
    """FilterSet for DellScanRange (search across name and targets)."""

    class Meta:
        """Django-filters Meta: bind filterset to DellScanRange."""

        model = DellScanRange
        fields = ["enabled"]

    def search(self, queryset, _name, value):
        """Full-text search across name and targets (the 'q' filter)."""
        return queryset.filter(
            Q(name__icontains=value) | Q(targets__icontains=value)
        )
