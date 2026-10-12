"""Transactional point services.

Every public function here is the only supported way to move points. Each runs
inside ``transaction.atomic()``, locks the accounts it touches with
``select_for_update()`` in ascending ``user_id`` order (so two operations that
touch the same pair can never deadlock), and writes the cached totals with
``save(update_fields=[...])`` after the lock. Direct ``PointAccount`` updates
and direct ledger writes are rejected by the models themselves.

Idempotency: when a caller passes ``idempotency_key`` the ledger stores the
SHA-256 of the operation arguments alongside it. A repeated call with the same
key and arguments replays the earlier result with ``created=False``; the same
key with different arguments raises :class:`IdempotencyConflictError`. Reserve,
capture and release also derive a deterministic key when none is passed, so a
retried capture or release cannot apply twice.
"""

import hashlib
import json
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from points.exceptions import (
    IdempotencyConflictError,
    InsufficientPointsError,
)
from points.models import PointAccount, PointReservation, PointTransaction


class GrantResult(NamedTuple):
    transaction: PointTransaction
    account: PointAccount
    created: bool


class TransferResult(NamedTuple):
    debit: PointTransaction
    credit: PointTransaction
    created: bool


class ReservationResult(NamedTuple):
    reservation: PointReservation
    transaction: PointTransaction
    created: bool


class ReconciliationResult(NamedTuple):
    before_available: int
    before_reserved: int
    after_available: int
    after_reserved: int
    repaired: bool


# --- argument handling --------------------------------------------------------


def _require_positive_int(amount, name="amount"):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError(f"{name} must be an integer.")
    if amount <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return amount


def _require_nonzero_int(amount, name="amount"):
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ValueError(f"{name} must be an integer.")
    if amount == 0:
        raise ValueError(f"{name} must not be zero.")
    return amount


def _validate_bucket(bucket):
    if bucket not in PointTransaction.Bucket.values:
        raise ValueError(f"Unknown point bucket {bucket!r}.")
    return bucket


def _require_staff_actor(actor):
    if actor is None:
        return
    if not getattr(actor, "is_staff", False):
        raise PermissionDenied("Only staff (or a system call) may do this.")


def _digest(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _actor_id(actor):
    return getattr(actor, "pk", None)


# --- database helpers ---------------------------------------------------------


def _lock_accounts(account_ids):
    """Lock every requested account in ascending ``user_id`` order.

    The single ``SELECT ... FOR UPDATE ... ORDER BY user_id`` statement means
    two operations that touch overlapping accounts acquire the locks in the same
    order, so they cannot deadlock each other.
    """

    ids = list(dict.fromkeys(account_ids))
    locked = list(
        PointAccount.objects.select_for_update().filter(pk__in=ids).order_by("user_id")
    )
    by_pk = {account.pk: account for account in locked}
    missing = [pk for pk in ids if pk not in by_pk]
    if missing:
        raise PointAccount.DoesNotExist(f"Unknown point account ids: {missing}")
    return by_pk


def _account_for_user(user):
    account, _created = PointAccount.objects.get_or_create(user=user)
    return account


def _create_transaction(**kwargs):
    """Create one ledger row. Extracted so a test can inject a mid-write failure."""

    return PointTransaction.objects.create(**kwargs)


def _existing_transaction(account, key):
    if not key:
        return None
    return PointTransaction.objects.filter(account=account, idempotency_key=key).first()


def _verify_repeat(existing, digest, description):
    if existing.arguments_digest != digest:
        raise IdempotencyConflictError(
            f"Idempotency key {existing.idempotency_key!r} was already used for a "
            f"different {description}."
        )


def _derive_reservation_key(
    account, amount, bucket, source_reference, recipient, actor, reason
):
    payload = {
        "operation": "reserve",
        "account": account.pk,
        "amount": amount,
        "bucket": bucket,
        "source_reference": source_reference,
        "recipient": getattr(recipient, "pk", None),
        "actor": _actor_id(actor),
        "reason": reason,
    }
    return f"reserve:{_digest(payload)[:40]}"


# --- services -----------------------------------------------------------------


@transaction.atomic
def ensure_account(user):
    """Return the user's account, creating it exactly once.

    Safe to call concurrently: ``get_or_create`` handles the losing INSERT, and
    the returned row is locked for the caller's transaction.
    """

    account, _created = PointAccount.objects.get_or_create(user=user)
    return PointAccount.objects.select_for_update().get(pk=account.pk)


@transaction.atomic
def issue_points(
    account,
    amount,
    *,
    actor,
    source_reference,
    bucket,
    idempotency_key=None,
    reason="",
):
    """Credit ``amount`` points to ``account`` (system or staff action)."""

    amount = _require_positive_int(amount)
    _validate_bucket(bucket)
    _require_staff_actor(actor)
    digest = _digest(
        {
            "operation": "issue_points",
            "account": account.pk,
            "amount": amount,
            "bucket": bucket,
            "source_reference": source_reference,
            "actor": _actor_id(actor),
            "reason": reason,
        }
    )
    locked = _lock_accounts([account.pk])[account.pk]
    existing = _existing_transaction(locked, idempotency_key)
    if existing is not None:
        _verify_repeat(existing, digest, "issue")
        return GrantResult(transaction=existing, account=locked, created=False)

    locked.available += amount
    locked.save(update_fields=["available", "reserved", "updated_at"])
    entry = _create_transaction(
        account=locked,
        amount=amount,
        bucket=bucket,
        type=PointTransaction.Type.ISSUE,
        actor=actor,
        source_reference=source_reference,
        idempotency_key=idempotency_key,
        arguments_digest=digest,
        reason=reason,
    )
    return GrantResult(transaction=entry, account=locked, created=True)


@transaction.atomic
def transfer(
    from_account,
    to_account,
    amount,
    *,
    actor,
    source_reference,
    bucket,
    idempotency_key=None,
    reason="",
):
    """Move ``amount`` from ``from_account`` to ``to_account`` in one transaction."""

    amount = _require_positive_int(amount)
    _validate_bucket(bucket)
    if from_account.pk == to_account.pk:
        raise ValueError("Cannot transfer points to the same account.")
    digest = _digest(
        {
            "operation": "transfer",
            "from_account": from_account.pk,
            "to_account": to_account.pk,
            "amount": amount,
            "bucket": bucket,
            "source_reference": source_reference,
            "actor": _actor_id(actor),
            "reason": reason,
        }
    )
    locked = _lock_accounts([from_account.pk, to_account.pk])
    payer = locked[from_account.pk]
    recipient = locked[to_account.pk]
    existing = _existing_transaction(payer, idempotency_key)
    if existing is not None:
        _verify_repeat(existing, digest, "transfer")
        credit = None
        if idempotency_key:
            credit = PointTransaction.objects.filter(
                account=recipient, idempotency_key=idempotency_key
            ).first()
        return TransferResult(debit=existing, credit=credit, created=False)

    if payer.available < amount:
        raise InsufficientPointsError("Insufficient available points for transfer.")

    payer.available -= amount
    recipient.available += amount
    payer.save(update_fields=["available", "reserved", "updated_at"])
    recipient.save(update_fields=["available", "reserved", "updated_at"])
    common = {
        "bucket": bucket,
        "type": PointTransaction.Type.TRANSFER,
        "actor": actor,
        "source_reference": source_reference,
        "idempotency_key": idempotency_key,
        "arguments_digest": digest,
        "reason": reason,
    }
    debit = _create_transaction(account=payer, amount=-amount, **common)
    credit = _create_transaction(account=recipient, amount=amount, **common)
    return TransferResult(debit=debit, credit=credit, created=True)


@transaction.atomic
def reserve(
    account,
    amount,
    *,
    actor,
    source_reference,
    bucket,
    idempotency_key=None,
    recipient=None,
    reason="",
):
    """Hold ``amount`` on ``account`` and record a ``reserved`` reservation."""

    amount = _require_positive_int(amount)
    _validate_bucket(bucket)
    key = idempotency_key or _derive_reservation_key(
        account, amount, bucket, source_reference, recipient, actor, reason
    )
    digest = _digest(
        {
            "operation": "reserve",
            "account": account.pk,
            "amount": amount,
            "bucket": bucket,
            "source_reference": source_reference,
            "recipient": getattr(recipient, "pk", None),
            "actor": _actor_id(actor),
            "reason": reason,
        }
    )
    locked = _lock_accounts([account.pk])[account.pk]
    existing = _existing_transaction(locked, key)
    if existing is not None:
        _verify_repeat(existing, digest, "reservation")
        reservation = PointReservation.objects.filter(ledger_key=key).first()
        if reservation is None:
            raise IdempotencyConflictError(
                "The reserve entry exists but its reservation record is missing."
            )
        return ReservationResult(
            reservation=reservation, transaction=existing, created=False
        )

    if locked.available < amount:
        raise InsufficientPointsError("Insufficient available points to reserve.")

    locked.available -= amount
    locked.reserved += amount
    locked.save(update_fields=["available", "reserved", "updated_at"])
    entry = _create_transaction(
        account=locked,
        amount=-amount,
        bucket=bucket,
        type=PointTransaction.Type.RESERVE,
        actor=actor,
        source_reference=source_reference,
        idempotency_key=key,
        arguments_digest=digest,
        reason=reason,
    )
    reservation = PointReservation.objects.create(
        account=locked,
        recipient=recipient,
        amount=amount,
        state=PointReservation.State.RESERVED,
        source_reference=source_reference,
        bucket=bucket,
        actor=actor,
        ledger_key=key,
    )
    return ReservationResult(reservation=reservation, transaction=entry, created=True)


@transaction.atomic
def capture(reservation, *, actor, idempotency_key=None, recipient=None, reason=""):
    """Credit a settled reservation to its recipient and lower the payer's hold."""

    reservation = PointReservation.objects.select_for_update().get(pk=reservation.pk)
    if (
        recipient is not None
        and reservation.recipient_id is not None
        and recipient.pk != reservation.recipient_id
    ):
        raise ValueError("Recipient contradicts the reservation's stored recipient.")
    effective_recipient = recipient if recipient is not None else reservation.recipient
    if effective_recipient is None:
        raise ValueError("Capture requires a resolvable recipient.")

    key = idempotency_key or f"{reservation.ledger_key}:capture"
    digest = _digest(
        {
            "operation": "capture",
            "reservation": reservation.pk,
            "recipient": effective_recipient.pk,
            "actor": _actor_id(actor),
            "reason": reason,
        }
    )
    recipient_account = _account_for_user(effective_recipient)
    locked = _lock_accounts([reservation.account_id, recipient_account.pk])
    payer = locked[reservation.account_id]
    recipient_account = locked[recipient_account.pk]

    existing = _existing_transaction(recipient_account, key)
    if existing is not None:
        _verify_repeat(existing, digest, "capture")
        return ReservationResult(
            reservation=reservation, transaction=existing, created=False
        )
    if reservation.state != PointReservation.State.RESERVED:
        raise ValueError("Reservation is already captured or released.")

    payer.reserved -= reservation.amount
    recipient_account.available += reservation.amount
    payer.save(update_fields=["available", "reserved", "updated_at"])
    recipient_account.save(update_fields=["available", "reserved", "updated_at"])
    entry = _create_transaction(
        account=recipient_account,
        amount=reservation.amount,
        bucket=reservation.bucket,
        type=PointTransaction.Type.CAPTURE,
        actor=actor,
        source_reference=reservation.source_reference,
        idempotency_key=key,
        arguments_digest=digest,
        reason=reason,
    )
    reservation.state = PointReservation.State.CAPTURED
    reservation.resolved_at = timezone.now()
    reservation.resolution_reason = reason
    reservation.save(update_fields=["state", "resolved_at", "resolution_reason"])
    return ReservationResult(reservation=reservation, transaction=entry, created=True)


@transaction.atomic
def release(reservation, *, actor, idempotency_key=None, reason=""):
    """Return a held reservation to its payer's available balance."""

    reservation = PointReservation.objects.select_for_update().get(pk=reservation.pk)
    key = idempotency_key or f"{reservation.ledger_key}:release"
    digest = _digest(
        {
            "operation": "release",
            "reservation": reservation.pk,
            "actor": _actor_id(actor),
            "reason": reason,
        }
    )
    locked = _lock_accounts([reservation.account_id])[reservation.account_id]
    existing = _existing_transaction(locked, key)
    if existing is not None:
        _verify_repeat(existing, digest, "release")
        return ReservationResult(
            reservation=reservation, transaction=existing, created=False
        )
    if reservation.state != PointReservation.State.RESERVED:
        raise ValueError("Reservation is already captured or released.")

    locked.available += reservation.amount
    locked.reserved -= reservation.amount
    locked.save(update_fields=["available", "reserved", "updated_at"])
    entry = _create_transaction(
        account=locked,
        amount=reservation.amount,
        bucket=reservation.bucket,
        type=PointTransaction.Type.RELEASE,
        actor=actor,
        source_reference=reservation.source_reference,
        idempotency_key=key,
        arguments_digest=digest,
        reason=reason,
    )
    reservation.state = PointReservation.State.RELEASED
    reservation.resolved_at = timezone.now()
    reservation.resolution_reason = reason
    reservation.save(update_fields=["state", "resolved_at", "resolution_reason"])
    return ReservationResult(reservation=reservation, transaction=entry, created=True)


@transaction.atomic
def adjust(
    account,
    amount,
    *,
    actor,
    source_reference,
    reason,
    idempotency_key=None,
):
    """Write a signed compensating entry (staff or system only)."""

    amount = _require_nonzero_int(amount)
    _require_staff_actor(actor)
    if not (reason or "").strip():
        raise ValueError("An adjustment requires a reason.")
    digest = _digest(
        {
            "operation": "adjust",
            "account": account.pk,
            "amount": amount,
            "actor": _actor_id(actor),
            "source_reference": source_reference,
            "reason": reason,
        }
    )
    locked = _lock_accounts([account.pk])[account.pk]
    existing = _existing_transaction(locked, idempotency_key)
    if existing is not None:
        _verify_repeat(existing, digest, "adjustment")
        return GrantResult(transaction=existing, account=locked, created=False)
    if locked.available + amount < 0:
        raise InsufficientPointsError(
            "Adjustment would make the available balance negative."
        )

    locked.available += amount
    locked.save(update_fields=["available", "reserved", "updated_at"])
    entry = _create_transaction(
        account=locked,
        amount=amount,
        bucket=PointTransaction.Bucket.ADJUSTMENT,
        type=PointTransaction.Type.ADJUSTMENT,
        actor=actor,
        source_reference=source_reference,
        idempotency_key=idempotency_key,
        arguments_digest=digest,
        reason=reason,
    )
    return GrantResult(transaction=entry, account=locked, created=True)


@transaction.atomic
def reconcile_account(account):
    """Rebuild cached totals from the ledger and open reservations.

    Repairs only the cache. It never invents or destroys points: correcting
    ownership is done with :func:`adjust`, which writes a compensating entry.
    """

    locked = PointAccount.objects.select_for_update().get(pk=account.pk)
    ledger_available = locked.transactions.aggregate(total=Sum("amount"))["total"] or 0
    ledger_reserved = (
        locked.reservations.filter(state=PointReservation.State.RESERVED).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    before_available = locked.available
    before_reserved = locked.reserved
    repaired = (
        before_available != ledger_available or before_reserved != ledger_reserved
    )
    if repaired:
        locked.available = ledger_available
        locked.reserved = ledger_reserved
        locked.save(update_fields=["available", "reserved", "updated_at"])
    return ReconciliationResult(
        before_available=before_available,
        before_reserved=before_reserved,
        after_available=ledger_available,
        after_reserved=ledger_reserved,
        repaired=repaired,
    )
