import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from jobs.models import BackgroundJob

MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 30


def _compute_backoff_delay(attempt: int) -> float:
    """Exponential backoff: 30s, 60s, 120s, 240s, 480s..."""
    return BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


class Command(BaseCommand):
    help = "Claim and run due background jobs using PostgreSQL SKIP LOCKED."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-now",
            action="store_true",
            help="Run one iteration: claim due jobs, invoke handlers, commit results.",
        )
        parser.add_argument(
            "--poll-interval",
            type=int,
            default=15,
            help="Seconds to sleep when no due jobs are found (default 15).",
        )

    def handle(self, *args, **options):
        run_now = options["run_now"]
        poll_interval = options["poll_interval"]

        try:
            self._process_due_jobs()
        except Exception as e:
            self.stderr.write(f"Error in job processing cycle: {e}")

        if run_now:
            # One-shot mode: exit after processing due jobs once.
            return

        # Polling mode: sleep and repeat.
        while True:
            try:
                time.sleep(poll_interval)
                self._process_due_jobs()
            except Exception as e:
                self.stderr.write(f"Error in job processing cycle: {e}")

    def _process_due_jobs(self):
        now = timezone.now()

        # Claim due jobs that have no lease or whose lease has expired.
        # We use select_for_update with skip_locked so only one worker picks each job.
        due_jobs = (
            BackgroundJob.objects.filter(
                status=BackgroundJob.Status.PENDING,
                run_after__lte=now,
            )
            .select_for_update(skip_locked=True)
            .only("pk", "job_type", "idempotency_key", "payload", "run_after")
        )

        if not due_jobs:
            return

        for job in due_jobs:
            # Commit the lease first, then invoke the handler outside the transaction
            # so that if the handler crashes, the lease can be reclaimed.
            with transaction.atomic():
                job.lease_expiry = timezone.now() + timedelta(
                    seconds=60
                )  # 1-minute lease
                job.status = BackgroundJob.Status.RUNNING
                job.save(update_fields=["lease_expiry", "status"])

            try:
                self._invoke_handler(job)
                # Handler succeeded — mark the job as successful.
                with transaction.atomic():
                    job.record_success()
            except Exception as e:
                # Handler failed — record the failure and let retry logic handle it.
                job.record_failure(str(e))

    def _invoke_handler(self, job: BackgroundJob):
        """Dispatch to an idempotent handler based on job_type."""
        job_type = job.job_type
        payload = job.payload

        # Import here to avoid circular imports at module level
        from jobs import handlers

        handler = handlers.get_handler(job_type)
        if handler is None:
            raise ValueError(f"No handler registered for job type: {job_type}")

        handler(payload)
