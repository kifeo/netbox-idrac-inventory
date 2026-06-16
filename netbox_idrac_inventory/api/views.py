# REST API views for netbox_idrac_inventory.
#
# NetBoxModelViewSet (confirmed from NetBox 4.x docs) handles bulk operations
# and object-level validation on top of DRF's ModelViewSet. All plugin
# ViewSets should extend it.

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from netbox.api.viewsets import NetBoxModelViewSet

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


class DellServerViewSet(NetBoxModelViewSet):
    """ViewSet for DellServer objects.

    Adds a ``sync`` action (POST /api/plugins/idrac-inventory/servers/<id>/sync/)
    that enqueues a background sync job and returns HTTP 202 with the job id.
    """

    # Annotate component_count so the serializer's source="components.count"
    # resolves without an extra DB hit on list endpoints.
    queryset = DellServer.objects.prefetch_related(
        "device",
        "components",
        "tags",
    )
    serializer_class = DellServerSerializer

    @property
    def filterset_class(self):
        # Lazy import: filtersets.py is written concurrently by another agent.
        from netbox_idrac_inventory.filtersets import DellServerFilterSet
        return DellServerFilterSet

    @action(detail=True, methods=["post"], url_path="sync")
    def sync(self, request, pk=None):
        """Enqueue a background iDRAC sync job for this server.

        Returns HTTP 202 Accepted with the enqueued job's id and URL so the
        caller can poll for completion.
        """
        # Lazy import: jobs.py is written concurrently by another agent.
        from netbox_idrac_inventory.jobs import enqueue_sync

        server = self.get_object()
        job = enqueue_sync(server, user=request.user)

        return Response(
            {
                "job_id": job.pk,
                "job_url": request.build_absolute_uri(
                    f"/api/extras/jobs/{job.pk}/"
                ),
                "message": f"Sync job enqueued for {server}.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class DellComponentViewSet(NetBoxModelViewSet):
    """ViewSet for DellComponent objects."""

    queryset = DellComponent.objects.prefetch_related(
        "server",
        "tags",
    )
    serializer_class = DellComponentSerializer

    @property
    def filterset_class(self):
        # Lazy import: filtersets.py is written concurrently by another agent.
        from netbox_idrac_inventory.filtersets import DellComponentFilterSet
        return DellComponentFilterSet


class DellScanRangeViewSet(NetBoxModelViewSet):
    """ViewSet for DellScanRange objects.

    Adds a ``run`` action that enqueues a discovery job (HTTP 202).
    """

    queryset = DellScanRange.objects.prefetch_related("tags")
    serializer_class = DellScanRangeSerializer

    @property
    def filterset_class(self):
        from netbox_idrac_inventory.filtersets import DellScanRangeFilterSet
        return DellScanRangeFilterSet

    @action(detail=True, methods=["post"], url_path="run")
    def run(self, request, pk=None):
        """Enqueue a discovery job for this scan range."""
        from netbox_idrac_inventory.jobs import enqueue_discovery

        scan_range = self.get_object()
        job = enqueue_discovery(scan_range, user=request.user)
        return Response(
            {
                "job_id": job.pk,
                "job_url": request.build_absolute_uri(
                    f"/api/extras/jobs/{job.pk}/"
                ),
                "message": f"Discovery job enqueued for {scan_range}.",
            },
            status=status.HTTP_202_ACCEPTED,
        )
