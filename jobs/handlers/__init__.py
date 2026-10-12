import time

from django.db import transaction
from django.db.models import F

from jobs.models import BackgroundJob


def _job_dedup_key(job_type, payload):
    """Build a deterministic dedup key from job type and payload references."""
    refs = payload.get("references", [])
    return f"{job_type}:{','.join(str(r) for r in sorted(refs))}"


# Registry: job_type -> handler function
_handoffers = {}


def register_handler(job_type):
    """Decorator to register a handler for a given job type."""

    def wrapper(func):
        _handoffers[job_type] = func
        return func

    return wrapper


def get_handler(job_type):
    return _handoffers.get(job_type)


def handle_job(job_type, payload):
    """Public entrypoint: look up and invoke the handler for a job type."""
    handler = get_handler(job_type)
    if handler is None:
        raise ValueError(f"No handler registered for job type: {job_type}")
    handler(payload)


@register_handler("test_dedup")
def _test_dedup_handler(payload):
    """No-op idempotent handler for test deduplication."""
    # Simulate work
    time.sleep(0.01)


@register_handler("test_retry")
def _test_retry_handler(payload):
    """Handler that fails first then succeeds on retry."""
    attempt = payload.get("attempt", 1)
    if attempt == 1:
        raise RuntimeError("Transient failure on attempt 1")
    # Succeed on subsequent attempts
    with transaction.atomic():
        BackgroundJob.objects.filter(idempotency_key=payload.get("_dedup_key")).update(
            attempt_count=F("attempt_count"),
            status="success",
        )
