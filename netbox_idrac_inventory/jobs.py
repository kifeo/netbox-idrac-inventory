"""
NetBox background job for synchronising a DellServer from iDRAC.

Confirmed NetBox 4.x API details (verified against a running NetBox 4.2,
2026-06):
  - ``JobRunner`` lives at ``netbox.jobs.JobRunner``.
  - Subclass must implement ``run(self, *args, **kwargs)``.
  - The runner only exposes ``self.job``; there is no ``self.logger``.
    Use the standard ``logging`` module for diagnostics.
  - The associated model instance is ``self.job.object`` (set via the
    ``instance=`` kwarg at enqueue time). The model must include
    ``JobsMixin`` for the Job framework to accept the association.
  - Enqueue a job:  ``MyJob.enqueue(instance=<obj>, user=<user>)``
  - Jobs do not return a value; exceptions propagate and mark the job
    as "errored" automatically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from netbox.jobs import JobRunner, system_job  # confirmed import path
from netbox.plugins import get_plugin_config

from netbox_idrac_inventory.idrac.sync import PLUGIN_NAME, sync_server

if TYPE_CHECKING:
    from users.models import User

    from netbox_idrac_inventory.models import DellScanRange, DellServer

logger = logging.getLogger("netbox.plugins.netbox_idrac_inventory")


class DellSyncJob(JobRunner):
    """
    Background job that synchronises a single ``DellServer`` from iDRAC.

    Enqueue via the module-level helper::

        from netbox_idrac_inventory.jobs import enqueue_sync
        job = enqueue_sync(server, user=request.user)

    Or directly::

        DellSyncJob.enqueue(instance=server, user=request.user)
    """

    class Meta:
        name = "Dell iDRAC Sync"

    def run(self, *args, **kwargs) -> None:
        """
        Execute the sync for the associated ``DellServer``.

        ``self.job.object`` is the ``DellServer`` instance (set because the
        job was enqueued with ``instance=server``).

        Any exception raised by ``sync_server`` propagates here so that
        NetBox marks the job as "errored".  ``sync_server`` guarantees that
        the ``DellServer`` row has already been saved with
        ``sync_status=FAILED`` before re-raising, so the database state is
        always consistent regardless of the job's outcome.
        """
        server: "DellServer" = self.job.object

        logger.info("DellSyncJob starting for server %s", server)

        result = sync_server(server, logger=logger)

        # Surface the summary dict in the job's ``data`` field so component
        # counts show on the job detail page.
        try:
            self.job.data = result
            self.job.save(update_fields=["data"])
        except Exception as exc:
            # Non-fatal: the sync itself succeeded; just note we couldn't
            # persist the result dict onto the job record.
            logger.warning("Could not persist sync result to job data: %s", exc)

        logger.info("DellSyncJob finished: %s", result.get("message", "done"))


# ---------------------------------------------------------------------------
# Module-level convenience helper
# ---------------------------------------------------------------------------


def enqueue_sync(server: "DellServer", user: "User | None" = None):
    """
    Enqueue a ``DellSyncJob`` for *server* and return the created ``Job``.

    Parameters
    ----------
    server:
        The ``DellServer`` instance to synchronise.
    user:
        The NetBox ``User`` who initiated the sync (optional; used for the
        job audit trail).

    Returns
    -------
    netbox.models.Job
        The newly created Job object.

    Example
    -------
    ::

        from netbox_idrac_inventory.jobs import enqueue_sync
        job = enqueue_sync(server, user=request.user)
        # job.pk can be used to redirect to the job detail page
    """
    return DellSyncJob.enqueue(instance=server, user=user)


# ---------------------------------------------------------------------------
# Recurring system job: sync every Dell server
# ---------------------------------------------------------------------------


class DellSyncAllJob(JobRunner):
    """
    Recurring system job that syncs every DellServer.

    Registered as a NetBox system job only when ``sync_interval_minutes`` > 0
    (see below); otherwise syncing stays manual / on-demand. One server's
    failure is logged and does not stop the others.
    """

    class Meta:
        name = "Dell iDRAC Sync (all servers)"

    def run(self, *args, **kwargs) -> None:
        from netbox_idrac_inventory.models import DellServer

        ok = failed = 0
        for server in DellServer.objects.all():
            try:
                sync_server(server)
                ok += 1
            except Exception as exc:
                failed += 1
                logger.warning("Scheduled sync failed for %s: %s", server, exc)
        logger.info("Scheduled Dell sync complete: %d ok, %d failed.", ok, failed)


# Register the recurring system job only when an interval is configured. The
# rqworker schedules registered system jobs (with their interval) at startup.
_sync_interval = get_plugin_config(PLUGIN_NAME, "sync_interval_minutes")
if _sync_interval and int(_sync_interval) > 0:
    system_job(interval=int(_sync_interval))(DellSyncAllJob)


# ---------------------------------------------------------------------------
# Scan-range discovery
# ---------------------------------------------------------------------------


class DellDiscoveryJob(JobRunner):
    """Background job that scans a DellScanRange and imports reachable iDRACs."""

    class Meta:
        name = "Dell iDRAC Discovery"

    def run(self, *args, **kwargs) -> None:
        from netbox_idrac_inventory.idrac.discovery import discover_range

        discover_range(self.job.object, logger=logger)


def enqueue_discovery(scan_range: "DellScanRange", user: "User | None" = None):
    """Enqueue a discovery job for *scan_range* and return the Job."""
    return DellDiscoveryJob.enqueue(instance=scan_range, user=user)
