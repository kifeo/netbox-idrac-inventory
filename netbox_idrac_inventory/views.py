"""UI views: CRUD for DellServer/DellComponent plus the sync trigger."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from netbox.views.generic import (
    ObjectDeleteView,
    ObjectEditView,
    ObjectListView,
    ObjectView,
    BulkDeleteView,
)

from .filtersets import (
    DellComponentFilterSet,
    DellScanRangeFilterSet,
    DellServerFilterSet,
)
from .forms import (
    DellComponentFilterForm,
    DellComponentForm,
    DellScanRangeFilterForm,
    DellScanRangeForm,
    DellServerFilterForm,
    DellServerForm,
)
from .models import DellComponent, DellScanRange, DellServer
from .tables import DellComponentTable, DellScanRangeTable, DellServerTable


# ---------------------------------------------------------------------------
# DellServer views
# ---------------------------------------------------------------------------


class DellServerListView(ObjectListView):
    queryset = DellServer.objects.prefetch_related("device").annotate(
        component_count=Count("components")
    )
    table = DellServerTable
    filterset = DellServerFilterSet
    filterset_form = DellServerFilterForm


class DellServerView(ObjectView):
    queryset = DellServer.objects.prefetch_related("components", "device")

    def get_extra_context(self, request, instance):
        components_table = DellComponentTable(
            instance.components.all(),
            orderable=True,
        )
        components_table.configure(request)
        return {
            "components_table": components_table,
        }


class DellServerEditView(ObjectEditView):
    queryset = DellServer.objects.all()
    form = DellServerForm


class DellServerDeleteView(ObjectDeleteView):
    queryset = DellServer.objects.all()


class DellServerBulkDeleteView(BulkDeleteView):
    queryset = DellServer.objects.all()
    filterset = DellServerFilterSet
    table = DellServerTable


# ---------------------------------------------------------------------------
# DellServer sync view (POST-only, plain Django View)
# ---------------------------------------------------------------------------


class DellServerSyncView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Enqueues a background sync job for a single DellServer.

    Requires change permission on DellServer. The sync job module is imported
    lazily so this module loads even if jobs.py hasn't been written yet.
    """

    permission_required = "netbox_idrac_inventory.change_dellserver"

    def post(self, request, pk):
        server = get_object_or_404(DellServer, pk=pk)
        # Lazy import: jobs.py is written by a concurrent agent
        from netbox_idrac_inventory.jobs import enqueue_sync

        enqueue_sync(server, user=request.user)
        messages.success(request, f"Sync job queued for {server}.")
        return redirect(server.get_absolute_url())


# ---------------------------------------------------------------------------
# DellComponent views
# ---------------------------------------------------------------------------


class DellComponentListView(ObjectListView):
    queryset = DellComponent.objects.select_related("server__device")
    table = DellComponentTable
    filterset = DellComponentFilterSet
    filterset_form = DellComponentFilterForm


class DellComponentView(ObjectView):
    queryset = DellComponent.objects.select_related("server__device")


class DellComponentEditView(ObjectEditView):
    queryset = DellComponent.objects.all()
    form = DellComponentForm


class DellComponentDeleteView(ObjectDeleteView):
    queryset = DellComponent.objects.all()


class DellComponentBulkDeleteView(BulkDeleteView):
    queryset = DellComponent.objects.all()
    filterset = DellComponentFilterSet
    table = DellComponentTable


# ---------------------------------------------------------------------------
# DellScanRange views
# ---------------------------------------------------------------------------


class DellScanRangeListView(ObjectListView):
    queryset = DellScanRange.objects.all()
    table = DellScanRangeTable
    filterset = DellScanRangeFilterSet
    filterset_form = DellScanRangeFilterForm


class DellScanRangeView(ObjectView):
    queryset = DellScanRange.objects.all()


class DellScanRangeEditView(ObjectEditView):
    queryset = DellScanRange.objects.all()
    form = DellScanRangeForm


class DellScanRangeDeleteView(ObjectDeleteView):
    queryset = DellScanRange.objects.all()


class DellScanRangeBulkDeleteView(BulkDeleteView):
    queryset = DellScanRange.objects.all()
    filterset = DellScanRangeFilterSet
    table = DellScanRangeTable


class DellScanRangeRunView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Enqueue a discovery job for a single scan range."""

    permission_required = "netbox_idrac_inventory.change_dellscanrange"

    def post(self, request, pk):
        scan_range = get_object_or_404(DellScanRange, pk=pk)
        from netbox_idrac_inventory.jobs import enqueue_discovery

        enqueue_discovery(scan_range, user=request.user)
        messages.success(request, f"Discovery job queued for {scan_range}.")
        return redirect(scan_range.get_absolute_url())
