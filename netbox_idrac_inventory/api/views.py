"""REST API viewsets, including the sync / discovery trigger actions."""

from django.db.models import Count
from netbox.api.viewsets import NetBoxModelViewSet
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.reverse import reverse

from netbox_idrac_inventory.filtersets import (
    DellComponentFilterSet,
    DellScanRangeFilterSet,
    DellServerFilterSet,
)
from netbox_idrac_inventory.jobs import enqueue_discovery, enqueue_sync
from netbox_idrac_inventory.models import (
    DellComponent,
    DellScanRange,
    DellServer,
)

from .serializers import (
    DellComponentSerializer,
    DellScanRangeSerializer,
    DellServerSerializer,
)


def _require_change_permission(request, model) -> None:
    """
    Enforce the model's *change* permission on a custom action.

    NetBox's DRF permission map ties POST to the *add* permission, which is
    the wrong semantic for "trigger a job on this object"; the UI views
    require change, so the API actions do too.
    """
    perm = f"{model._meta.app_label}.change_{model._meta.model_name}"
    if not request.user.has_perm(perm):
        raise PermissionDenied(f"This action requires the {perm} permission.")


def _job_response(request, job, message: str) -> Response:
    return Response(
        {
            "job_id": job.pk,
            "job_url": reverse(
                "core-api:job-detail", kwargs={"pk": job.pk}, request=request
            ),
            "message": message,
        },
        status=status.HTTP_202_ACCEPTED,
    )


class DellServerViewSet(NetBoxModelViewSet):
    """ViewSet for DellServer objects.

    Adds a ``sync`` action (POST /api/plugins/idrac-inventory/servers/<id>/sync/)
    that enqueues a background sync job and returns HTTP 202 with the job id.
    """

    # component_count feeds the serializer without loading every component.
    queryset = DellServer.objects.prefetch_related("device", "tags").annotate(
        component_count=Count("components")
    )
    serializer_class = DellServerSerializer
    filterset_class = DellServerFilterSet

    @action(detail=True, methods=["post"], url_path="sync")
    def sync(self, request, pk=None):
        """Enqueue a background iDRAC sync job for this server.

        Returns HTTP 202 Accepted with the enqueued job's id and URL so the
        caller can poll for completion.
        """
        _require_change_permission(request, DellServer)
        server = self.get_object()
        job = enqueue_sync(server, user=request.user)
        return _job_response(request, job, f"Sync job enqueued for {server}.")


class DellComponentViewSet(NetBoxModelViewSet):
    """ViewSet for DellComponent objects."""

    queryset = DellComponent.objects.prefetch_related("server", "tags")
    serializer_class = DellComponentSerializer
    filterset_class = DellComponentFilterSet


class DellScanRangeViewSet(NetBoxModelViewSet):
    """ViewSet for DellScanRange objects.

    Adds a ``run`` action that enqueues a discovery job (HTTP 202).
    """

    queryset = DellScanRange.objects.prefetch_related("tags")
    serializer_class = DellScanRangeSerializer
    filterset_class = DellScanRangeFilterSet

    @action(detail=True, methods=["post"], url_path="run")
    def run(self, request, pk=None):
        """Enqueue a discovery job for this scan range."""
        _require_change_permission(request, DellScanRange)
        scan_range = self.get_object()
        if not scan_range.enabled:
            return Response(
                {"detail": "This scan range is disabled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = enqueue_discovery(scan_range, user=request.user)
        return _job_response(
            request, job, f"Discovery job enqueued for {scan_range}."
        )
