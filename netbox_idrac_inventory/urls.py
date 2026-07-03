"""URL configuration for the netbox_idrac_inventory plugin.

URL names follow the NetBox 4.x plugin convention:
  <model>           -> detail view (pk)
  <model>_list      -> list view
  <model>_add       -> create view
  <model>_edit      -> edit view (pk)
  <model>_delete    -> delete view (pk)
  <model>_bulk_delete -> bulk delete
  <model>_changelog -> object changelog (pk)

All names are within the "netbox_idrac_inventory" namespace so they are
accessed as "plugins:netbox_idrac_inventory:<name>" from Python code.

Note: ObjectChangeLogView is the standard NetBox generic view for changelogs.
It expects a `model` kwarg; we pass it via path() defaults dict.
"""

from django.urls import path
from netbox.views.generic import ObjectChangeLogView

from .models import DellComponent, DellScanRange, DellServer
from .views import (
    DellComponentBulkDeleteView,
    DellComponentDeleteView,
    DellComponentEditView,
    DellComponentListView,
    DellComponentView,
    DellScanRangeBulkDeleteView,
    DellScanRangeDeleteView,
    DellScanRangeEditView,
    DellScanRangeListView,
    DellScanRangeRunView,
    DellScanRangeView,
    DellServerBulkDeleteView,
    DellServerBulkSyncView,
    DellServerDeleteView,
    DellServerEditView,
    DellServerListView,
    DellServerSyncView,
    DellServerView,
)

urlpatterns = [
    # ------------------------------------------------------------------
    # DellServer
    # ------------------------------------------------------------------
    path(
        "servers/",
        DellServerListView.as_view(),
        name="dellserver_list",
    ),
    path(
        "servers/add/",
        DellServerEditView.as_view(),
        name="dellserver_add",
    ),
    path(
        "servers/<int:pk>/",
        DellServerView.as_view(),
        name="dellserver",
    ),
    path(
        "servers/<int:pk>/edit/",
        DellServerEditView.as_view(),
        name="dellserver_edit",
    ),
    path(
        "servers/<int:pk>/delete/",
        DellServerDeleteView.as_view(),
        name="dellserver_delete",
    ),
    path(
        "servers/<int:pk>/sync/",
        DellServerSyncView.as_view(),
        name="dellserver_sync",
    ),
    path(
        "servers/<int:pk>/changelog/",
        ObjectChangeLogView.as_view(),
        name="dellserver_changelog",
        kwargs={"model": DellServer},
    ),
    path(
        "servers/delete/",
        DellServerBulkDeleteView.as_view(),
        name="dellserver_bulk_delete",
    ),
    path(
        "servers/sync/",
        DellServerBulkSyncView.as_view(),
        name="dellserver_bulk_sync",
    ),
    # ------------------------------------------------------------------
    # DellComponent
    # ------------------------------------------------------------------
    path(
        "components/",
        DellComponentListView.as_view(),
        name="dellcomponent_list",
    ),
    path(
        "components/add/",
        DellComponentEditView.as_view(),
        name="dellcomponent_add",
    ),
    path(
        "components/<int:pk>/",
        DellComponentView.as_view(),
        name="dellcomponent",
    ),
    path(
        "components/<int:pk>/edit/",
        DellComponentEditView.as_view(),
        name="dellcomponent_edit",
    ),
    path(
        "components/<int:pk>/delete/",
        DellComponentDeleteView.as_view(),
        name="dellcomponent_delete",
    ),
    path(
        "components/<int:pk>/changelog/",
        ObjectChangeLogView.as_view(),
        name="dellcomponent_changelog",
        kwargs={"model": DellComponent},
    ),
    path(
        "components/delete/",
        DellComponentBulkDeleteView.as_view(),
        name="dellcomponent_bulk_delete",
    ),
    # ------------------------------------------------------------------
    # DellScanRange
    # ------------------------------------------------------------------
    path(
        "scan-ranges/",
        DellScanRangeListView.as_view(),
        name="dellscanrange_list",
    ),
    path(
        "scan-ranges/add/",
        DellScanRangeEditView.as_view(),
        name="dellscanrange_add",
    ),
    path(
        "scan-ranges/<int:pk>/",
        DellScanRangeView.as_view(),
        name="dellscanrange",
    ),
    path(
        "scan-ranges/<int:pk>/edit/",
        DellScanRangeEditView.as_view(),
        name="dellscanrange_edit",
    ),
    path(
        "scan-ranges/<int:pk>/delete/",
        DellScanRangeDeleteView.as_view(),
        name="dellscanrange_delete",
    ),
    path(
        "scan-ranges/<int:pk>/run/",
        DellScanRangeRunView.as_view(),
        name="dellscanrange_run",
    ),
    path(
        "scan-ranges/<int:pk>/changelog/",
        ObjectChangeLogView.as_view(),
        name="dellscanrange_changelog",
        kwargs={"model": DellScanRange},
    ),
    path(
        "scan-ranges/delete/",
        DellScanRangeBulkDeleteView.as_view(),
        name="dellscanrange_bulk_delete",
    ),
]
