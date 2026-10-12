"""Grant the configured starter points when an account becomes verified.

Both the email-verification view and the verified Google sign-in flow call
:func:`grant_starter_points` from inside their existing transaction, so the
verification and the grant commit or roll back together. The grant itself is a
single atomic block: it re-reads the user row, checks eligibility against that
fresh row, then creates (or reuses) the point account and writes one ``starter``
ledger entry through the point-ledger service.
"""

from django.conf import settings
from django.db import transaction

from accounts.models import User
from points import services
from points.exceptions import IdempotencyConflictError
from points.models import PointTransaction

BUCKET = "starter"


@transaction.atomic
def grant_starter_points(user):
    """Credit ``settings.STARTER_POINTS`` to a verified, active user once.

    Returns the :class:`points.services.GrantResult` when an entry is written,
    or ``None`` when the user is ineligible or the configured amount is not
    positive. The amount is read at grant time so ``override_settings`` works.

    The grant is idempotent per user regardless of the current
    ``STARTER_POINTS`` value: if a ``starter`` issue entry already exists for
    the derived key ``starter:{pk}``, the existing ledger row is returned with
    ``created=False`` and nothing is written, so changing the setting between
    verifications cannot lock a previously granted user out. If a concurrent
    grant wins the race and ``issue_points`` then raises
    :class:`IdempotencyConflictError`, that is treated as already-granted and
    the existing ledger row is returned.
    """

    amount = settings.STARTER_POINTS
    if amount <= 0:
        return None

    fresh = User.objects.select_for_update().get(pk=user.pk)
    if fresh.email_verified_at is None or fresh.state != User.State.ACTIVE:
        return None

    account = services.ensure_account(fresh)
    key = f"starter:{fresh.pk}"
    existing = PointTransaction.objects.filter(
        account=account,
        idempotency_key=key,
        bucket=BUCKET,
        type=PointTransaction.Type.ISSUE,
    ).first()
    if existing is not None:
        return services.GrantResult(
            transaction=existing, account=account, created=False
        )
    try:
        return services.issue_points(
            account,
            amount,
            actor=None,
            source_reference=f"user:{fresh.pk}",
            bucket=BUCKET,
            idempotency_key=key,
            reason="Starter points for a verified account",
        )
    except IdempotencyConflictError:
        existing = PointTransaction.objects.filter(
            account=account, idempotency_key=key
        ).first()
        if existing is not None:
            return services.GrantResult(
                transaction=existing, account=account, created=False
            )
        raise
