"""Registry of the background job types the application is allowed to store.

A job type is only persistable once it has been registered here, so an unknown
type is rejected at ``clean()``/``save()`` time and at enqueue time instead of
being silently written to the ``jobs_backgroundjob`` table.
"""

from django.core.exceptions import ValidationError

JOB_TYPE_MAX_LENGTH = 40

_allowed_job_types: set[str] = set()


class UnknownJobType(ValueError):
    """Raised when a job type is not present in the registry."""


def register_job_type(job_type: str) -> str:
    """Add ``job_type`` to the allowlist and return it."""
    if not isinstance(job_type, str) or not job_type.strip():
        raise ValueError("A job type must be a non-empty string.")
    if len(job_type) > JOB_TYPE_MAX_LENGTH:
        raise ValueError(f"Job type must be at most {JOB_TYPE_MAX_LENGTH} characters.")
    _allowed_job_types.add(job_type)
    return job_type


def unregister_job_type(job_type: str) -> None:
    """Remove ``job_type`` from the allowlist (mainly useful in tests)."""
    _allowed_job_types.discard(job_type)


def allowed_job_types() -> frozenset[str]:
    return frozenset(_allowed_job_types)


def is_allowed_job_type(job_type) -> bool:
    return isinstance(job_type, str) and job_type in _allowed_job_types


def validate_job_type(job_type):
    """Validate ``job_type`` for the enqueue service, raising ``UnknownJobType``."""
    if not is_allowed_job_type(job_type):
        raise UnknownJobType(
            f"{job_type!r} is not an allowed background job type. "
            f"Allowed types: {sorted(allowed_job_types()) or '(none registered)'}."
        )
    return job_type


def validate_job_type_value(job_type):
    """Model validator wrapper so unknown types fail ``full_clean()``."""
    if not is_allowed_job_type(job_type):
        raise ValidationError(
            "%(value)r is not an allowed background job type.",
            code="unknown_job_type",
            params={"value": job_type},
        )
