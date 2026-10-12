from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from jobs.job_types import JOB_TYPE_MAX_LENGTH, is_allowed_job_type
from jobs.sanitize import sanitize_error_summary


def max_attempts() -> int:
    """Maximum number of attempts before a job fails permanently.

    ``BACKGROUND_JOB_MAX_ATTEMPTS`` is the single source of truth: it is defined
    once in ``config/settings.py`` (itself overridable from the environment).
    There is deliberately no second, unreachable copy of the default here — a
    fallback that settings always overrides is misleading, and it silently
    disagrees with the configured value when it is changed.
    """
    return int(settings.BACKGROUND_JOB_MAX_ATTEMPTS)


def lease_seconds() -> int:
    return int(settings.BACKGROUND_JOB_LEASE_SECONDS)


def backoff_base_seconds() -> int:
    return int(settings.BACKGROUND_JOB_BACKOFF_BASE_SECONDS)


def backoff_max_seconds() -> int:
    return int(settings.BACKGROUND_JOB_BACKOFF_MAX_SECONDS)


def compute_backoff_delay(attempt: int) -> float:
    """Capped exponential backoff for the retry that follows ``attempt``.

    Attempt 1 waits ``base`` seconds, attempt 2 waits ``2 * base``, and so on,
    never exceeding ``BACKGROUND_JOB_BACKOFF_MAX_SECONDS``.
    """
    exponent = max(0, int(attempt) - 1)
    delay = backoff_base_seconds() * (2**exponent)
    return float(min(delay, backoff_max_seconds()))


class BackgroundJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PERMANENT_FAILURE = "permanent_failure", "Permanent failure"

    job_type = models.CharField(
        max_length=JOB_TYPE_MAX_LENGTH,
        help_text="Must be registered in jobs.job_types.",
    )
    idempotency_key = models.CharField(max_length=72, unique=True)
    payload = models.JSONField(
        help_text="Small JSON payload of record references; no media or secrets.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    run_after = models.DateTimeField(help_text="Earliest time the job may run.")
    lease_expiry = models.DateTimeField(null=True, blank=True)
    error_summary = models.TextField(
        blank=True, help_text="Sanitized summary; no secrets or media bytes."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("run_after", "pk")
        indexes = [
            models.Index(fields=["status", "lease_expiry", "run_after"]),
        ]

    def __str__(self):
        return f"{self.job_type}:{self.idempotency_key}"

    def clean(self):
        """Reject job types that are not in the ``jobs.job_types`` allowlist."""
        super().clean()
        if not is_allowed_job_type(self.job_type):
            raise ValidationError(
                {
                    "job_type": [
                        "%(value)r is not an allowed background job type; "
                        "register it with jobs.job_types.register_job_type()."
                        % {"value": self.job_type}
                    ]
                }
            )

    def save(self, *args, validate: bool = True, **kwargs):
        """Validate on every write unless ``validate=False`` is passed.

        The worker passes ``validate=False`` for its own status transitions: it
        never changes ``job_type``, and the allowlist is per process, so a
        worker that has not imported a handler module must still be able to
        record success or permanent failure.
        """
        if validate:
            self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_over_max_attempts(self):
        return self.attempt_count >= max_attempts()

    @property
    def has_live_lease(self) -> bool:
        return bool(self.lease_expiry and self.lease_expiry > timezone.now())

    def record_success(self):
        self.status = self.Status.SUCCESS
        self.lease_expiry = None
        self.error_summary = ""
        self.save(
            update_fields=["status", "lease_expiry", "error_summary"],
            validate=False,
        )

    def record_failure(
        self, error_summary: str = "", *, now=None, permanent: bool = False
    ):
        """Record a failed attempt and schedule (or decline) the retry.

        The attempt was already counted when the job was claimed, so this
        reschedules the retry with capped exponential backoff unless the job has
        used up ``BACKGROUND_JOB_MAX_ATTEMPTS`` or the failure is permanent.
        """
        now = now or timezone.now()
        self.error_summary = sanitize_error_summary(error_summary)
        self.lease_expiry = None
        if permanent or self.is_over_max_attempts:
            self.status = self.Status.PERMANENT_FAILURE
            self.save(
                update_fields=["status", "error_summary", "lease_expiry"],
                validate=False,
            )
            return self.Status.PERMANENT_FAILURE

        self.status = self.Status.PENDING
        self.run_after = now + timedelta(
            seconds=compute_backoff_delay(self.attempt_count)
        )
        self.save(
            update_fields=["status", "error_summary", "lease_expiry", "run_after"],
            validate=False,
        )
        return self.Status.PENDING

    def extend_lease(self, *, seconds: int | None = None):
        seconds = lease_seconds() if seconds is None else seconds
        self.lease_expiry = timezone.now() + timedelta(seconds=seconds)
        self.save(update_fields=["lease_expiry"], validate=False)
