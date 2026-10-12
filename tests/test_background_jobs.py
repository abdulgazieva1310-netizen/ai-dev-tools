"""Tests for the durable background job queue.

The row locking behaviour (SKIP LOCKED, competing workers, expired lease
recovery) only exists on PostgreSQL. Those tests call ``pytest.fail()`` when the
suite is pointed at SQLite while the job test file is being run explicitly, so
they can never pass silently on a backend that ignores the feature.
"""

import logging
import os
import sys
import threading
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from accounts.models import User
from jobs import worker
from jobs.enqueue import build_idempotency_key, enqueue
from jobs.handlers import register_handler
from jobs.job_types import (
    UnknownJobType,
    register_job_type,
    unregister_job_type,
)
from jobs.models import (
    BackgroundJob,
    backoff_base_seconds,
    compute_backoff_delay,
    max_attempts,
)
from jobs.sanitize import sanitize_error_summary

HANDLER_CALLS: list[tuple[str, dict]] = []
FLAKY_FAILURES_REMAINING = {"count": 0}
SECRET_FAILURE = {"error": RuntimeError("boom")}


def require_postgres():
    """Guard for PostgreSQL-only assertions."""
    if connection.vendor == "postgresql":
        return
    if os.environ.get("RUN_POSTGRES_JOB_TESTS") == "1" or any(
        argument.endswith("tests/test_background_jobs.py") for argument in sys.argv
    ):
        pytest.fail(
            "Background job row locking needs the Compose PostgreSQL database; "
            f"the configured backend is {connection.vendor}."
        )
    pytest.skip("PostgreSQL-only background job tests run in Docker Compose.")


@register_handler("test_noop")
def _noop_handler(payload):
    HANDLER_CALLS.append(("test_noop", payload))


@register_handler("test_flaky")
def _flaky_handler(payload):
    HANDLER_CALLS.append(("test_flaky", payload))
    if FLAKY_FAILURES_REMAINING["count"] > 0:
        FLAKY_FAILURES_REMAINING["count"] -= 1
        raise RuntimeError("upstream timeout password=hunter2 " + "detail " * 60)


@register_handler("test_idempotent")
def _idempotent_handler(payload):
    """Idempotent by construction: get_or_create keyed on the user id."""
    from profiles.models import Profile

    HANDLER_CALLS.append(("test_idempotent", payload))
    user = User.objects.get(pk=payload["user_id"])
    Profile.objects.get_or_create(
        user=user, defaults={"display_name": f"member-{user.pk}"}
    )


@register_handler("test_secret")
def _secret_handler(payload):
    """Raise a caller supplied exception, to exercise summary sanitization."""
    HANDLER_CALLS.append(("test_secret", payload))
    raise SECRET_FAILURE["error"]


@pytest.fixture(autouse=True)
def _clean_handler_state():
    HANDLER_CALLS.clear()
    FLAKY_FAILURES_REMAINING["count"] = 0
    SECRET_FAILURE["error"] = RuntimeError("boom")
    yield
    HANDLER_CALLS.clear()
    FLAKY_FAILURES_REMAINING["count"] = 0
    SECRET_FAILURE["error"] = RuntimeError("boom")


@pytest.fixture
def user(db):
    return User.objects.create_user("jobs@example.com", password="password")


def make_due_job(job_type="test_noop", key="k", **kwargs):
    kwargs.setdefault("payload", {"references": [1]})
    kwargs.setdefault("run_after", timezone.now() - timedelta(seconds=5))
    return enqueue(job_type, kwargs.pop("payload"), idempotency_key=key, **kwargs).job


# --- criterion: allowlisted job type -----------------------------------------


@pytest.mark.django_db
def test_enqueue_rejects_unknown_job_type():
    with pytest.raises(UnknownJobType):
        enqueue("not_registered_type", {"references": [1]}, idempotency_key="unknown")
    assert not BackgroundJob.objects.exists()


@pytest.mark.django_db
def test_model_rejects_unknown_job_type_on_save():
    job = BackgroundJob(
        job_type="not_registered_type",
        idempotency_key="unknown-model",
        payload={"references": [1]},
        run_after=timezone.now(),
    )
    with pytest.raises(Exception) as error:
        job.save()
    assert "job_type" in str(error.value)
    assert not BackgroundJob.objects.exists()


@pytest.mark.django_db
def test_registered_job_type_round_trips(user):
    register_job_type("test_allowlist_round_trip")
    try:
        result = enqueue(
            "test_allowlist_round_trip", {"references": [user.pk]}, idempotency_key="ok"
        )
        assert result.created
        assert result.job.status == BackgroundJob.Status.PENDING
    finally:
        unregister_job_type("test_allowlist_round_trip")


# --- criterion: enqueue service, same transaction, deduplication --------------


@pytest.mark.django_db(transaction=True)
def test_enqueue_rolls_back_with_the_calling_transaction(user):
    class EventRejected(Exception):
        pass

    with pytest.raises(EventRejected):
        with transaction.atomic():
            enqueue("test_noop", {"references": [user.pk]}, idempotency_key="rolled")
            assert BackgroundJob.objects.filter(idempotency_key="rolled").exists()
            raise EventRejected
    assert not BackgroundJob.objects.filter(idempotency_key="rolled").exists()


@pytest.mark.django_db(transaction=True)
def test_enqueue_commits_with_the_calling_transaction(user):
    with transaction.atomic():
        result = enqueue("test_noop", {"references": [user.pk]}, idempotency_key="kept")
    assert result.created
    assert BackgroundJob.objects.filter(pk=result.job.pk).exists()


@pytest.mark.django_db
def test_enqueue_deduplicates_by_idempotency_key():
    first = enqueue("test_noop", {"references": [1]}, idempotency_key="dedup-key")
    second = enqueue("test_noop", {"references": [2]}, idempotency_key="dedup-key")

    assert first.created
    assert not second.created
    assert first.job.pk == second.job.pk
    assert BackgroundJob.objects.count() == 1
    assert BackgroundJob.objects.get().payload == {"references": [1]}


@pytest.mark.django_db
def test_derived_idempotency_key_is_deterministic():
    assert build_idempotency_key(
        "test_noop", {"references": [1]}
    ) == build_idempotency_key("test_noop", {"references": [1]})
    assert build_idempotency_key(
        "test_noop", {"references": [1]}
    ) != build_idempotency_key("test_noop", {"references": [2]})
    assert len(build_idempotency_key("test_noop", {"references": [1]})) <= 72

    one = enqueue("test_noop", {"references": [1]})
    two = enqueue("test_noop", {"references": [1]})
    assert one.job.pk == two.job.pk
    assert not two.created


@pytest.mark.django_db
def test_enqueue_rejects_oversized_or_sensitive_payloads():
    with pytest.raises(ValueError, match="password"):
        enqueue(
            "test_noop", {"user_id": 1, "password": "hunter2"}, idempotency_key="p1"
        )
    with pytest.raises(ValueError, match="record reference"):
        enqueue("test_noop", {"note": "x" * 500}, idempotency_key="p2")
    with pytest.raises(ValueError, match="payload is larger"):
        enqueue(
            "test_noop",
            {"refs": [f"{index}" + "z" * 50 for index in range(100)]},
            idempotency_key="p3",
        )
    assert not BackgroundJob.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_enqueue_deduplicates_on_postgres():
    require_postgres()

    start = threading.Barrier(6)
    results: list[object] = [None] * 6

    def worker_thread(index):
        connection.close()
        try:
            start.wait(timeout=10)
            results[index] = enqueue(
                "test_noop", {"references": [index]}, idempotency_key="race-key"
            )
        except Exception as error:  # pragma: no cover - surfaced by the assert
            results[index] = error
        finally:
            connection.close()

    threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not [r for r in results if isinstance(r, Exception)], results
    pks = {result.job.pk for result in results}
    assert len(pks) == 1
    assert BackgroundJob.objects.count() == 1


# --- criterion: claim with row locks, lease, success/failure ------------------


@pytest.mark.django_db
def test_run_jobs_command_runs_due_jobs_only(user):
    due = make_due_job(key="due")
    not_due = make_due_job(key="later", run_after=timezone.now() + timedelta(hours=1))

    call_command("run_jobs", "--run-now")

    due.refresh_from_db()
    not_due.refresh_from_db()
    assert due.status == BackgroundJob.Status.SUCCESS
    assert due.attempt_count == 1
    assert due.lease_expiry is None
    assert not_due.status == BackgroundJob.Status.PENDING
    assert not_due.attempt_count == 0


@pytest.mark.django_db
def test_success_clears_lease_and_error_summary(user):
    job = make_due_job(key="cleared")
    job.record_failure("RuntimeError: boom", now=timezone.now())
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.PENDING

    job.record_success()
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.SUCCESS
    assert job.lease_expiry is None
    assert job.error_summary == ""


# --- criterion: capped exponential backoff and max attempts -------------------


@pytest.mark.django_db
def test_failure_reschedules_with_exponential_backoff(user):
    FLAKY_FAILURES_REMAINING["count"] = 2
    job = make_due_job("test_flaky", key="flaky")

    before = timezone.now()
    worker.run_once()
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.PENDING
    assert job.attempt_count == 1
    delay = (job.run_after - before).total_seconds()
    assert 25 <= delay <= 40, delay

    job.run_after = timezone.now() - timedelta(seconds=1)
    job.save(update_fields=["run_after"])

    before = timezone.now()
    worker.run_once()
    job.refresh_from_db()
    assert job.attempt_count == 2
    delay = (job.run_after - before).total_seconds()
    assert 55 <= delay <= 70, delay
    assert job.status == BackgroundJob.Status.PENDING


@pytest.mark.django_db
def test_backoff_is_capped():
    base = 30
    assert compute_backoff_delay(1) == base
    assert compute_backoff_delay(2) == base * 2
    assert compute_backoff_delay(3) == base * 4
    assert compute_backoff_delay(20) == 3600


@pytest.mark.django_db
def test_retry_stops_at_max_attempts(user):
    job = make_due_job("test_flaky", key="exhausted")

    for attempt in range(1, 6):
        FLAKY_FAILURES_REMAINING["count"] = 1
        job.refresh_from_db()
        job.run_after = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["run_after"])
        worker.run_once()
        job.refresh_from_db()
        assert job.attempt_count == attempt

    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE
    assert job.lease_expiry is None

    FLAKY_FAILURES_REMAINING["count"] = 1
    worker.run_once()
    job.refresh_from_db()
    assert job.attempt_count == 5
    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE


@pytest.mark.django_db
@override_settings(BACKGROUND_JOB_MAX_ATTEMPTS=2)
def test_max_attempts_is_configurable(user):
    job = make_due_job("test_flaky", key="configured")

    for _ in range(2):
        FLAKY_FAILURES_REMAINING["count"] = 1
        job.refresh_from_db()
        job.run_after = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["run_after"])
        worker.run_once()

    job.refresh_from_db()
    assert job.attempt_count == 2
    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE


def test_job_limits_are_read_from_settings_with_the_documented_defaults():
    assert settings.BACKGROUND_JOB_MAX_ATTEMPTS == 5
    assert settings.BACKGROUND_JOB_BACKOFF_BASE_SECONDS == 30
    assert max_attempts() == settings.BACKGROUND_JOB_MAX_ATTEMPTS
    assert backoff_base_seconds() == 30
    assert compute_backoff_delay(1) == 30


@override_settings(
    BACKGROUND_JOB_MAX_ATTEMPTS=9,
    BACKGROUND_JOB_LEASE_SECONDS=120,
    BACKGROUND_JOB_BACKOFF_BASE_SECONDS=3,
)
def test_configured_job_limits_are_the_ones_that_are_used():
    assert max_attempts() == 9
    assert worker.lease_seconds() == 120
    assert compute_backoff_delay(1) == 3


def test_job_defaults_are_not_duplicated_in_the_jobs_package():
    """`config/settings.py` is the only definition of the retry/backoff limits.

    A second copy in `jobs/` can never win, and only invites the two drifting
    apart (mutation testing showed the old fallback was dead code).
    """
    from jobs import models

    for name in (
        "DEFAULT_MAX_ATTEMPTS",
        "DEFAULT_BACKOFF_BASE_SECONDS",
        "DEFAULT_BACKOFF_MAX_SECONDS",
    ):
        assert not hasattr(models, name), f"jobs.models.{name} is a shadowed default"
    assert not hasattr(worker, "DEFAULT_BATCH_SIZE")


@pytest.mark.django_db
def test_error_summary_is_sanitized_and_truncated(user, caplog):
    FLAKY_FAILURES_REMAINING["count"] = 1
    job = make_due_job("test_flaky", key="sanitized")
    with caplog.at_level(logging.WARNING, logger="jobs.worker"):
        worker.run_once()
    job.refresh_from_db()

    assert "hunter2" not in job.error_summary
    assert "[redacted]" in job.error_summary
    assert len(job.error_summary) <= 200
    assert "RuntimeError" in job.error_summary
    assert "hunter2" not in caplog.text


# --- criterion: no secret reaches error_summary or payload --------------------

# Every shape here leaked at least one credential value into the durable row.
AUTHORIZATION_SECRET = "sk-live-SECRET-TOKEN-123456"
AUTHORIZATION_ERROR = (
    f"RuntimeError: connect failed: Authorization: Bearer {AUTHORIZATION_SECRET}"
)

LEAKED_SUMMARY_SHAPES = [
    pytest.param(
        AUTHORIZATION_ERROR,
        AUTHORIZATION_SECRET,
        id="authorization-bearer",
    ),
    pytest.param(
        "HTTPError: client_secret: abc123 rejected", "abc123", id="client-secret"
    ),
    pytest.param(
        "trace: Set-Cookie: sessionid=abc123def", "abc123def", id="set-cookie"
    ),
    pytest.param(
        "token=Bearer sk-live-1234567890", "sk-live-1234567890", id="token-bearer"
    ),
    pytest.param("api_key=abc123xyz", "abc123xyz", id="api-key"),
    pytest.param("x-api-key: abc123xyz rejected", "abc123xyz", id="prefixed-api-key"),
    pytest.param("password: 's3cret-value'", "s3cret-value", id="quoted-password"),
    pytest.param(
        'send failed headers={"Authorization": "Bearer sk-live-abc123"}',
        "sk-live-abc123",
        id="header-dict",
    ),
    pytest.param(
        "unauthorized sk-live-SECRET-TOKEN-123456 for user 7",
        "sk-live-SECRET-TOKEN-123456",
        id="bare-provider-token",
    ),
]


@pytest.mark.parametrize("message, secret", LEAKED_SUMMARY_SHAPES)
def test_error_summary_removes_the_credential_not_just_the_keyword(message, secret):
    summary = sanitize_error_summary(message)

    assert secret not in summary, summary
    assert "[redacted]" in summary, summary
    # Redaction must be stable: the worker sanitizes before logging and the model
    # sanitizes again when the failure is recorded.
    assert sanitize_error_summary(summary) == summary


@pytest.mark.django_db
def test_error_summary_still_keeps_the_surrounding_message():
    summary = sanitize_error_summary(AUTHORIZATION_ERROR)
    assert summary.startswith("RuntimeError: connect failed:")
    assert AUTHORIZATION_SECRET not in summary


@pytest.mark.django_db
@pytest.mark.parametrize("message, secret", LEAKED_SUMMARY_SHAPES)
def test_persisted_error_summary_never_contains_the_secret(
    message, secret, caplog, request
):
    SECRET_FAILURE["error"] = RuntimeError(message)
    job = make_due_job("test_secret", key=f"secret-{request.node.callspec.id}")

    with caplog.at_level(logging.WARNING, logger="jobs.worker"):
        worker.run_once()

    job.refresh_from_db()
    stored = BackgroundJob.objects.get(pk=job.pk).error_summary
    assert secret not in stored, stored
    assert secret not in job.error_summary, job.error_summary
    assert secret not in caplog.text
    assert "[redacted]" in stored


@pytest.mark.django_db
def test_summary_of_a_long_secret_free_error_is_still_truncated():
    summary = sanitize_error_summary("RuntimeError: " + "detail " * 60)
    assert len(summary) <= 200
    assert summary.endswith("...")
    assert "RuntimeError" in summary


LEAKED_PAYLOAD_VALUES = [
    pytest.param(
        {"note": "my token is Bearer sk-live-PAYLOAD-LEAK-9988"},
        id="bearer-token",
    ),
    pytest.param({"note": "sk-live-PAYLOAD-LEAK-9988"}, id="bare-provider-token"),
    pytest.param({"note": "client_secret: abc123"}, id="client-secret"),
    pytest.param({"note": "sessionid=abc123def"}, id="session-id"),
    pytest.param({"note": "api_key=abc123xyz"}, id="api-key"),
    pytest.param({"s": "A" * 33}, id="opaque-run"),
    pytest.param(
        {"nested": {"note": "Bearer sk-live-PAYLOAD-LEAK-9988"}},
        id="nested-secret",
    ),
    pytest.param(
        {"refs": [1, "Bearer sk-live-PAYLOAD-LEAK-9988"]}, id="secret-in-list"
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", LEAKED_PAYLOAD_VALUES)
def test_payload_values_that_look_like_secrets_are_rejected(payload):
    with pytest.raises(ValueError, match="looks like a credential"):
        enqueue("test_noop", payload, idempotency_key="leaky-payload")

    assert not BackgroundJob.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key", ["client_secret", "set-cookie", "aws_secret_access_key", "x-api-token"]
)
def test_payload_keys_that_look_sensitive_are_rejected(key):
    with pytest.raises(ValueError, match="looks sensitive"):
        enqueue("test_noop", {"user_id": 1, key: "value"}, idempotency_key=f"key-{key}")

    assert not BackgroundJob.objects.exists()


@pytest.mark.django_db
def test_record_references_are_still_accepted():
    result = enqueue(
        "test_noop",
        {"listing_id": 42, "external_id": "123e4567-e89b-12d3-a456-426614174000"},
        idempotency_key="references-ok",
    )

    assert result.created
    assert BackgroundJob.objects.get().payload == {
        "listing_id": 42,
        "external_id": "123e4567-e89b-12d3-a456-426614174000",
    }


@pytest.mark.django_db
def test_job_without_handler_fails_permanently(user):
    register_job_type("test_no_handler")
    job = make_due_job("test_no_handler", key="no-handler")
    worker.run_once()
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE
    assert "no handler" in job.error_summary
    unregister_job_type("test_no_handler")


@pytest.mark.django_db
def test_worker_without_the_registered_type_still_records_failure(user):
    """A worker process that has not imported the handler must still recover."""
    register_job_type("test_out_of_process")
    job = make_due_job("test_out_of_process", key="out-of-process")
    unregister_job_type("test_out_of_process")

    worker.run_once()
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE


# --- criterion: handler idempotency ------------------------------------------


@pytest.mark.django_db
def test_handler_is_idempotent_when_a_job_runs_twice(user):
    job = make_due_job("test_idempotent", key="idem", payload={"user_id": user.pk})

    worker.process_job(job)
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.SUCCESS

    # Simulate a redelivery of the same job (lease reclaimed after a crash).
    job.status = BackgroundJob.Status.RUNNING
    job.save(update_fields=["status"])
    worker.process_job(job)

    from profiles.models import Profile

    assert Profile.objects.filter(user=user).count() == 1


# --- criterion: lease recovery and PostgreSQL row locks -----------------------


@pytest.mark.django_db
def test_live_lease_job_is_not_claimed(user):
    job = make_due_job(key="live")
    job.status = BackgroundJob.Status.RUNNING
    job.attempt_count = 1
    job.lease_expiry = timezone.now() + timedelta(seconds=60)
    job.save(update_fields=["status", "attempt_count", "lease_expiry"])

    assert worker.claim_due_jobs() == []
    job.refresh_from_db()
    assert job.attempt_count == 1
    assert job.has_live_lease


@pytest.mark.django_db
def test_expired_lease_is_reclaimed(user):
    job = make_due_job(key="expired")
    job.status = BackgroundJob.Status.RUNNING
    job.attempt_count = 1
    job.lease_expiry = timezone.now() - timedelta(seconds=1)
    job.save(update_fields=["status", "attempt_count", "lease_expiry"])

    claimed = worker.claim_due_jobs()
    assert [claimed_job.pk for claimed_job in claimed] == [job.pk]

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.RUNNING
    assert job.attempt_count == 2
    assert job.has_live_lease

    # The reclaimed lease still blocks a concurrent second worker.
    assert worker.claim_due_jobs() == []

    worker.process_job(job)
    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.SUCCESS
    assert [call[0] for call in HANDLER_CALLS] == ["test_noop"]


@pytest.mark.django_db(transaction=True)
def test_claim_skips_rows_locked_by_another_worker_on_postgres(user):
    require_postgres()

    locked = make_due_job(key="locked")
    free = make_due_job(key="free")
    locked_event = threading.Event()
    release_event = threading.Event()
    errors: list[Exception] = []

    def lock_holder():
        connection.close()
        try:
            with transaction.atomic():
                list(BackgroundJob.objects.select_for_update().filter(pk=locked.pk))
                locked_event.set()
                release_event.wait(timeout=10)
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    thread = threading.Thread(target=lock_holder)
    thread.start()
    assert locked_event.wait(timeout=10), "helper thread never took the row lock"

    try:
        started = timezone.now()
        claimed = worker.claim_due_jobs(limit=10)
        elapsed = (timezone.now() - started).total_seconds()
    finally:
        release_event.set()
        thread.join(timeout=15)

    assert not errors, errors
    assert [job.pk for job in claimed] == [free.pk]
    assert elapsed < 2, f"claim blocked on the locked row for {elapsed:.2f}s"

    locked.refresh_from_db()
    assert locked.status == BackgroundJob.Status.PENDING
    free.refresh_from_db()
    assert free.status == BackgroundJob.Status.RUNNING


@pytest.mark.django_db(transaction=True)
def test_competing_workers_claim_each_job_once_on_postgres(user):
    require_postgres()

    jobs = [make_due_job(key=f"competing-{index}") for index in range(8)]
    start = threading.Barrier(4)
    claimed_ids: list[list[int]] = [[] for _ in range(4)]
    errors: list[Exception] = []

    def competing_worker(index):
        connection.close()
        try:
            start.wait(timeout=10)
            claimed_ids[index] = [job.pk for job in worker.claim_due_jobs(limit=8)]
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=competing_worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    claimed = [pk for batch in claimed_ids for pk in batch]
    assert sorted(claimed) == sorted(job.pk for job in jobs)
    assert len(claimed) == len(set(claimed)), "a job was claimed by two workers"

    for job in BackgroundJob.objects.all():
        assert job.attempt_count == 1
        assert job.status == BackgroundJob.Status.RUNNING
        assert job.has_live_lease
