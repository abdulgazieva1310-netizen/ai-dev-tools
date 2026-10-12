"""Point accounts, the append-only ledger, and reservation holds.

The model layer enforces two invariants so that no other app can quietly break
the ledger:

* ``PointTransaction`` rows are append-only. The manager forbids ``update()``
  and ``delete()``, and ``save()`` refuses to touch a row that already exists.
* Cached ``PointAccount.available``/``reserved`` totals are written only by
  ``points.services``. The manager forbids ``update()``, and ``save()`` refuses
  to write the totals unless the caller opened :func:`balance_write`; the services
  change the totals with ``save(update_fields=[...])`` after locking the row.

Every balance the product shows is a cache of ``PointTransaction.amount`` (for
``available``) and of the still-``reserved`` ``PointReservation`` rows (for
``reserved``); ``points.services.reconcile_account`` can rebuild them.
"""

import contextlib
import contextvars

from django.conf import settings
from django.db import models

from points.exceptions import ImmutableLedgerError, ProtectedBalanceError

#: Whether the current call stack is allowed to write the cached totals.
_balance_write_permitted = contextvars.ContextVar(
    "points_balance_write_permitted", default=False
)


@contextlib.contextmanager
def balance_write():
    """Permit ``PointAccount.save()`` to write ``available``/``reserved``.

    Only ``points.services`` opens this context; every other code path that tries
    to persist the totals raises :class:`ProtectedBalanceError`.
    """

    token = _balance_write_permitted.set(True)
    try:
        yield
    finally:
        _balance_write_permitted.reset(token)


class PointAccountQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ProtectedBalanceError(
            "PointAccount totals are managed by points.services; call a service "
            "function instead of updating the cache directly."
        )


class PointAccountManager(models.Manager.from_queryset(PointAccountQuerySet)):
    pass


class PointAccount(models.Model):
    _PROTECTED_FIELDS = frozenset({"available", "reserved"})
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="point_account",
    )
    available = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PointAccountManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(available__gte=0),
                name="point_account_available_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved__gte=0),
                name="point_account_reserved_nonnegative",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and not _balance_write_permitted.get():
            update_fields = kwargs.get("update_fields")
            if update_fields is None or self._PROTECTED_FIELDS.intersection(
                update_fields
            ):
                raise ProtectedBalanceError(
                    "PointAccount totals are managed by points.services; call a "
                    "service function instead of saving the cache directly."
                )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"PointAccount<user={self.user_id}>"


class PointTransactionQuerySet(models.QuerySet):
    def update(self, *args, **kwargs):
        raise ImmutableLedgerError(
            "Point ledger entries are append-only and cannot be updated."
        )

    def delete(self, *args, **kwargs):
        raise ImmutableLedgerError(
            "Point ledger entries are append-only and cannot be deleted."
        )


class PointTransactionManager(models.Manager.from_queryset(PointTransactionQuerySet)):
    pass


class PointTransaction(models.Model):
    class Type(models.TextChoices):
        ISSUE = "issue", "Issue"
        TRANSFER = "transfer", "Transfer"
        RESERVE = "reserve", "Reserve"
        RELEASE = "release", "Release"
        CAPTURE = "capture", "Capture"
        ADJUSTMENT = "adjustment", "Adjustment"

    class Bucket(models.TextChoices):
        STARTER = "starter", "Starter"
        BOOKING = "booking", "Booking"
        TRANSCRIPT = "transcript", "Transcript"
        TEACHING_REWARD = "teaching_reward", "Teaching reward"
        ADJUSTMENT = "adjustment", "Adjustment"
        GENERAL = "general", "General"

    account = models.ForeignKey(
        PointAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    amount = models.IntegerField(
        help_text="Signed points: positive credits, negative debits.",
    )
    bucket = models.CharField(max_length=20, choices=Bucket.choices)
    type = models.CharField(max_length=20, choices=Type.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="point_transactions",
    )
    source_reference = models.CharField(max_length=200, blank=True)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    arguments_digest = models.CharField(max_length=64, blank=True)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PointTransactionManager()

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0),
                name="point_transaction_amount_nonzero",
            ),
            models.UniqueConstraint(
                fields=("account", "idempotency_key"),
                name="unique_point_transaction_idempotency_key",
            ),
        ]
        indexes = [
            models.Index(fields=("account", "created_at")),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableLedgerError(
                "Point ledger entries are append-only and cannot be modified."
            )
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type} {self.amount:+d} (account={self.account_id})"


class PointReservation(models.Model):
    class State(models.TextChoices):
        RESERVED = "reserved", "Reserved"
        CAPTURED = "captured", "Captured"
        RELEASED = "released", "Released"

    account = models.ForeignKey(
        PointAccount,
        on_delete=models.PROTECT,
        related_name="reservations",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="point_reservations_received",
    )
    amount = models.PositiveIntegerField()
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.RESERVED
    )
    source_reference = models.CharField(max_length=200, blank=True)
    bucket = models.CharField(max_length=20, choices=PointTransaction.Bucket.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="point_reservations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_reason = models.TextField(blank=True)
    ledger_key = models.CharField(max_length=200)

    class Meta:
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="point_reservation_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=("reserved", "captured", "released")),
                name="point_reservation_state_allowed",
            ),
        ]

    def __str__(self):
        return f"PointReservation<{self.pk} {self.state} {self.amount}>"
