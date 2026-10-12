import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs import worker
from jobs.models import lease_seconds, max_attempts

logger = logging.getLogger(__name__)


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
            type=float,
            default=settings.BACKGROUND_JOB_POLL_INTERVAL,
            help="Seconds to sleep when no due jobs are found (default 5).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=settings.BACKGROUND_JOB_BATCH_SIZE,
            help="Maximum jobs claimed per iteration (default 10).",
        )

    def handle(self, *args, **options):
        poll_interval = options["poll_interval"]
        batch_size = options["batch_size"]
        self._running = True

        def stop(signum, frame):
            logger.info("run_jobs received signal %s; finishing current cycle", signum)
            self._running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        self.stdout.write(
            f"Worker starting: max_attempts={max_attempts()} "
            f"lease={lease_seconds()}s poll={poll_interval}s"
        )

        while self._running:
            processed = 0
            try:
                processed = worker.run_once(limit=batch_size)
            except Exception:  # noqa: BLE001 - a worker must survive one bad cycle
                logger.exception("Error in job processing cycle")
                self.stderr.write(self.style.ERROR("Error in job processing cycle"))
            if processed:
                self.stdout.write(f"Processed {processed} job(s)")
            if options["run_now"]:
                return
            if not processed and self._running:
                time.sleep(poll_interval)
