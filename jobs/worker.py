"""Claim and execute due background jobs.

The claim runs inside a single ``transaction.atomic()`` block so that
``SELECT ... FOR UPDATE SKIP LOCKED`` actually takes effect (PostgreSQL raises
``TransactionManagementError`` otherwise). Each claimed job gets a lease that is
committed *before* the handler runs, so a worker that dies mid-handler leaves a
reclaimable lease behind instead of holding an open row lock.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from jobs.handlers import get_handler
from jobs.models import BackgroundJob, lease_seconds
from jobs.sanitize import sanitize_error_summary

logger = logging.getLogger(__name__)


def _batch_size(limit=None) -> int:
    if limit is not None:
        return limit
    return int(settings.BACKGROUND_JOB_BATCH_SIZE)


def claim_due_jobs(*, now=None, limit=None) -> list[BackgroundJob]:
    """Claim due jobs and return them with a committed lease.

    A job is claimable when it is PENDING and due, or when it is RUNNING with a
    lease that has expired (the previous worker died before reporting back).
    Jobs with a live lease are never returned, so the same job cannot run
    concurrently.
    """
    now = now or timezone.now()
    limit = _batch_size(limit)
    lease_expiry = now + timedelta(seconds=lease_seconds())

    with transaction.atomic():
        due_ids = list(
            BackgroundJob.objects.filter(
                Q(status=BackgroundJob.Status.PENDING, run_after__lte=now)
                | Q(status=BackgroundJob.Status.RUNNING, lease_expiry__lte=now)
            )
            .order_by("run_after", "pk")
            .values_list("pk", flat=True)[:limit]
        )
        if not due_ids:
            return []

        claimed = list(
            BackgroundJob.objects.select_for_update(skip_locked=True)
            .filter(pk__in=due_ids)
            .order_by("run_after", "pk")
        )

        jobs = []
        for job in claimed:
            job.status = BackgroundJob.Status.RUNNING
            job.attempt_count += 1
            job.lease_expiry = lease_expiry
            job.error_summary = ""
            job.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "lease_expiry",
                    "error_summary",
                ],
                validate=False,
            )
            jobs.append(job)

    # Committed: the lease and the row locks are released before any handler runs.
    return jobs


def process_job(job: BackgroundJob, *, now=None) -> str:
    """Run one claimed job's handler and record the outcome."""
    handler = get_handler(job.job_type)
    if handler is None:
        logger.warning("No handler registered for job type %s", job.job_type)
        with transaction.atomic():
            job.record_failure(
                f"no handler registered for job type {job.job_type}",
                now=now,
                permanent=True,
            )
        return BackgroundJob.Status.PERMANENT_FAILURE

    try:
        handler(job.payload)
    except Exception as error:  # noqa: BLE001 - a failing handler is recorded
        summary = sanitize_error_summary(f"{type(error).__name__}: {error}")
        logger.warning(
            "Job %s failed on attempt %s: %s", job.pk, job.attempt_count, summary
        )
        with transaction.atomic():
            return job.record_failure(summary, now=now)

    with transaction.atomic():
        job.record_success()
    return BackgroundJob.Status.SUCCESS


def run_once(*, now=None, limit=None) -> int:
    """Claim and process one batch of due jobs. Returns the number processed."""
    jobs = claim_due_jobs(now=now, limit=limit)
    for job in jobs:
        process_job(job)
    return len(jobs)
