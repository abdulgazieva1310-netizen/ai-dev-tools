"""Registry of idempotent handlers, keyed by background job type.

Registering a handler also registers its job type in the allowlist, so a job
type without a handler can never be enqueued or stored.
"""

from jobs.job_types import register_job_type, unregister_job_type

_handlers: dict[str, object] = {}


class MissingHandler(LookupError):
    """Raised when no handler is registered for a job type."""


def register_handler(job_type):
    """Decorator registering an idempotent handler for ``job_type``."""

    def wrapper(func):
        register_job_type(job_type)
        _handlers[job_type] = func
        return func

    return wrapper


def unregister_handler(job_type):
    _handlers.pop(job_type, None)
    unregister_job_type(job_type)


def get_handler(job_type):
    return _handlers.get(job_type)


def handle_job(job_type, payload):
    """Look up and invoke the handler for ``job_type``."""
    handler = get_handler(job_type)
    if handler is None:
        raise MissingHandler(f"No handler registered for job type: {job_type}")
    return handler(payload)
