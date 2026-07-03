"""UI views: CRUD for DellServer/DellComponent plus the sync trigger."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from netbox.views.generic import (
    BulkDeleteView,
    ObjectDeleteView,
    ObjectEditView,
    ObjectListView,
    ObjectView,
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
from .jobs import enqueue_discovery, enqueue_sync
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
    # Adds a "Sync from iDRAC" button next to the bulk edit/delete actions.
    template_name = "netbox_idrac_inventory/dellserver_list.html"


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
    """Enqueue a background sync job for a single DellServer."""

    permission_required = "netbox_idrac_inventory.change_dellserver"

    def post(self, request, pk):
        server = get_object_or_404(DellServer, pk=pk)
        enqueue_sync(server, user=request.user)
        messages.success(request, f"Sync job queued for {server}.")
        return redirect(server.get_absolute_url())


class DellServerBulkSyncView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Enqueue sync jobs for the servers selected in the list view."""

    permission_required = "netbox_idrac_inventory.change_dellserver"

    def post(self, request):
        if request.POST.get("_all"):
            # "Select all matching query" — apply the list view's filters.
            servers = DellServerFilterSet(
                request.GET, queryset=DellServer.objects.all()
            ).qs
        else:
            servers = DellServer.objects.filter(
                pk__in=request.POST.getlist("pk")
            )
        count = 0
        for server in servers:
            enqueue_sync(server, user=request.user)
            count += 1
        if count:
            messages.success(request, f"Sync jobs queued for {count} servers.")
        else:
            messages.warning(request, "No servers selected for sync.")
        return redirect("plugins:netbox_idrac_inventory:dellserver_list")


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
        if not scan_range.enabled:
            messages.warning(
                request, f"Scan range {scan_range} is disabled; not queued."
            )
            return redirect(scan_range.get_absolute_url())
        enqueue_discovery(scan_range, user=request.user)
        messages.success(request, f"Discovery job queued for {scan_range}.")
        return redirect(scan_range.get_absolute_url())
