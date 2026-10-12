"""Exceptions raised by the point ledger.

The two protection errors also inherit from the built-in exception a caller
would most plausibly expect (``RuntimeError`` for a write that the model
forbids, ``ValueError`` for a key that is rebound to different arguments), so
callers can catch either the project type or the conventional one.
"""


class PointsError(Exception):
    """Base class for every point-ledger error."""


class InsufficientPointsError(PointsError):
    """The account cannot cover a debit or a reservation."""


class ImmutableLedgerError(PointsError, RuntimeError):
    """Code tried to update or delete an append-only ledger entry."""


class ProtectedBalanceError(PointsError, RuntimeError):
    """Code tried to change cached totals outside ``points.services``."""


class IdempotencyConflictError(PointsError, ValueError):
    """An idempotency key was reused with different arguments."""
