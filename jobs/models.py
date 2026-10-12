from django.db import models

JOB_TYPE_MAX_LENGTH = 40


class BackgroundJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PERMANENT_FAILURE = "permanent_failure", "Permanent failure"

    job_type = models.CharField(max_length=JOB_TYPE_MAX_LENGTH)
    idempotency_key = models.CharField(max_length=72, unique=True)
    payload = models.JSONField(
        help_text="Small JSON payload of record references; no media bytes or secrets."
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    run_after = models.DateTimeField()
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

    @property
    def is_over_max_attempts(self):
        return self.attempt_count >= 5

    def record_success(self):
        self.status = self.Status.SUCCESS
        self.attempt_count = 0
        self.lease_expiry = None
        self.save(update_fields=["status", "attempt_count", "lease_expiry"])

    def record_failure(self, error_summary: str):
        self.attempt_count += 1
        # Store a sanitized summary; truncate and mask secrets
        self.error_summary = error_summary[:200] if error_summary else ""
        self.status = (
            self.Status.PERMANENT_FAILURE
            if self.is_over_max_attempts
            else self.Status.PENDING
        )
        self.save(
            update_fields=[
                "attempt_count",
                "error_summary",
                "status",
            ]
        )
