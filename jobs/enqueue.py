"""Enqueue service for durable background jobs.

``enqueue()`` is the only supported way to create a ``BackgroundJob``. It is
safe to call from inside a caller's ``transaction.atomic()`` block: the job row
is written in that same transaction as the database event that required the
work, so a rolled back event leaves no orphaned job behind.

Repeated requests are deduplicated on ``idempotency_key`` with
``get_or_create()`` semantics: the second call returns the already existing job
instead of raising ``IntegrityError``, whether the duplicate is sequential or a
concurrent INSERT from another request.
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import NamedTuple

from django.db import IntegrityError, transaction
from django.utils import timezone

from jobs.job_types import JOB_TYPE_MAX_LENGTH, validate_job_type
from jobs.models import BackgroundJob
from jobs.sanitize import sanitize_payload

IDEMPOTENCY_KEY_MAX_LENGTH = 72
_KEY_DIGEST_LENGTH = 24


class EnqueueResult(NamedTuple):
    job: BackgroundJob
    created: bool


def build_idempotency_key(job_type, payload, *, scope: str = "") -> str:
    """Derive a deterministic idempotency key from a job type and payload.

    The same ``(job_type, scope, payload)`` triple always yields the same key,
    so callers that cannot manage keys themselves can rely on content based
    deduplication instead.
    """
    canonical = json.dumps(
        {"job_type": job_type, "scope": scope, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{job_type[:JOB_TYPE_MAX_LENGTH]}:{digest[:_KEY_DIGEST_LENGTH]}"


def enqueue(
    job_type: str,
    payload: dict | None = None,
    *,
    idempotency_key: str | None = None,
    scope: str = "",
    run_after: datetime | None = None,
    delay_seconds: float = 0,
) -> EnqueueResult:
    """Create (or fetch) a background job for ``job_type``.

    ``payload`` must be a small mapping of record references; media bytes and
    credentials are rejected by :func:`jobs.sanitize.sanitize_payload`.
    """
    validate_job_type(job_type)
    clean_payload = sanitize_payload(payload)

    if idempotency_key is None:
        idempotency_key = build_idempotency_key(job_type, clean_payload, scope=scope)
    elif not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("idempotency_key must be a non-empty string.")
    if len(idempotency_key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValueError(
            f"idempotency_key must be at most {IDEMPOTENCY_KEY_MAX_LENGTH} characters."
        )

    if run_after is None:
        run_after = timezone.now() + timedelta(seconds=delay_seconds)

    existing = BackgroundJob.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return EnqueueResult(job=existing, created=False)

    job = BackgroundJob(
        job_type=job_type,
        payload=clean_payload,
        idempotency_key=idempotency_key,
        run_after=run_after,
        status=BackgroundJob.Status.PENDING,
    )
    try:
        # The INSERT runs in its own savepoint, so a concurrent duplicate rolls
        # back only this statement instead of poisoning a caller's atomic block.
        # Uniqueness is enforced by the database here: a model level check would
        # raise ValidationError instead of letting the winner's row win.
        with transaction.atomic(using=BackgroundJob.objects.db):
            job.save(validate=False)
    except IntegrityError:
        existing = BackgroundJob.objects.get(idempotency_key=idempotency_key)
        return EnqueueResult(job=existing, created=False)
    return EnqueueResult(job=job, created=True)
