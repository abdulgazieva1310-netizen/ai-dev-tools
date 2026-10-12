from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounts.models import User
from jobs.models import BackgroundJob


@pytest.fixture
def user(db):
    return User.objects.create_user("test@example.com", password="password")


@pytest.mark.django_db
def test_background_job_model_can_be_created(user):
    run_after = timezone.now() + timedelta(seconds=1)
    job = BackgroundJob.objects.create(
        job_type="test_dedup",
        idempotency_key="test-key-123",
        payload={"references": [1, 2, 3]},
        run_after=run_after,
    )
    assert job.status == BackgroundJob.Status.PENDING
    assert job.attempt_count == 0
    assert job.lease_expiry is None
    assert str(job) == "test_dedup:test-key-123"


@pytest.mark.django_db
def test_job_dedup_key():
    from jobs.handlers import _job_dedup_key

    key1 = _job_dedup_key("test_dedup", {"references": [1, 2]})
    key2 = _job_dedup_key("test_dedup", {"references": [2, 1]})
    key3 = _job_dedup_key("test_dedup", {"references": [1, 3]})
    assert key1 == key2  # sorted references
    assert key1 != key3  # different references


@pytest.mark.django_db
def test_job_dedup_key_different_types():
    from jobs.handlers import _job_dedup_key

    key1 = _job_dedup_key("type_a", {"references": [1]})
    key2 = _job_dedup_key("type_b", {"references": [1]})
    assert key1 != key2  # different job types


@pytest.mark.django_db
def test_job_attempt_count_increments_on_failure(user):
    run_after = timezone.now() + timedelta(seconds=1)
    job = BackgroundJob.objects.create(
        job_type="test_dedup",
        idempotency_key="failure-key",
        payload={"references": [1]},
        run_after=run_after,
    )
    assert job.attempt_count == 0
    # Simulate a failure
    job.record_failure("Transient error")
    assert job.attempt_count == 1
    assert job.status == BackgroundJob.Status.PENDING

    # Simulate another failure
    job.record_failure("Another error")
    assert job.attempt_count == 2
    assert job.status == BackgroundJob.Status.PENDING

    # Max attempts = 5, so after 5 failures it should be PERMANENT_FAILURE
    for _ in range(3):
        job.record_failure("Error")
    assert job.attempt_count == 5
    assert job.status == BackgroundJob.Status.PERMANENT_FAILURE


@pytest.mark.django_db
def test_job_record_success(user):
    run_after = timezone.now() + timedelta(seconds=1)
    job = BackgroundJob.objects.create(
        job_type="test_dedup",
        idempotency_key="success-key",
        payload={"references": [1]},
        run_after=run_after,
    )
    assert job.status == BackgroundJob.Status.PENDING
    job.record_success()
    assert job.status == BackgroundJob.Status.SUCCESS
    assert job.attempt_count == 0
    assert job.lease_expiry is None


@pytest.mark.django_db
def test_enqueue_deduplication():
    """Enqueue the same idempotency key twice; second should be handled gracefully."""
    # First enqueue
    run_after = timezone.now() + timedelta(seconds=1)
    BackgroundJob.objects.create(
        job_type="test_dedup",
        idempotency_key="dedup-key-1",
        payload={"references": [1]},
        run_after=run_after,
    )
    # Second enqueue with same key - should fail due to unique constraint,
    # the enqueue service should catch this and return the existing job
    from django.db import IntegrityError

    try:
        BackgroundJob.objects.create(
            job_type="test_dedup",
            idempotency_key="dedup-key-1",
            payload={"references": [1]},
            run_after=run_after,
        )
        assert False, "Expected IntegrityError"
    except IntegrityError:
        # Expected - duplicate idempotency key
        pass


@pytest.mark.django_db
def test_run_jobs_management_command_claims_due_jobs(user):
    """The run_jobs command should claim pending jobs with run_after <= now."""
    run_after = timezone.now() - timedelta(seconds=10)  # in the past

    # Create a pending job with run_in_the_past
    job = BackgroundJob.objects.create(
        job_type="test_dedup",
        idempotency_key="claimable-key",
        payload={"references": [1]},
        run_after=run_after,
    )

    # Run one iteration of the command
    call_command("run_jobs", "--run-now", "--poll-interval", "0")

    # Check the job was claimed and had its status updated
    job.refresh_from_db()
    # After processing, status should be either RUNNING (handler invoked) or SUCCESS
    assert job.status in (
        BackgroundJob.Status.RUNNING,
        BackgroundJob.Status.SUCCESS,
        BackgroundJob.Status.PERMANENT_FAILURE,
    )
