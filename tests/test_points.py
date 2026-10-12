"""Tests for the transactional point ledger.

Row locking, concurrency and whole-transaction rollback only behave like
production on PostgreSQL, so those tests use ``require_postgres()``: when this
file is run explicitly against SQLite they fail loudly instead of passing for
the wrong reason, and an implicit whole-suite SQLite run skips them.

The remaining tests exercise the service surface on either backend.
"""

import os
import pathlib
import re
import sys
import threading
from unittest.mock import patch

import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.db.models import F, Sum
from django.test.utils import CaptureQueriesContext

from accounts.models import User
from points import services
from points.exceptions import (
    IdempotencyConflictError,
    ImmutableLedgerError,
    InsufficientPointsError,
    ProtectedBalanceError,
)
from points.models import PointAccount, PointReservation, PointTransaction


def require_postgres():
    """Guard for PostgreSQL-only assertions."""
    if connection.vendor == "postgresql":
        return
    if os.environ.get("RUN_POSTGRES_POINTS_TESTS") == "1" or any(
        argument.endswith("tests/test_points.py") for argument in sys.argv
    ):
        pytest.fail(
            "Point-ledger locking needs the Compose PostgreSQL database; "
            f"the configured backend is {connection.vendor}."
        )
    pytest.skip("PostgreSQL-only point-ledger tests run in Docker Compose.")


BUCKET = PointTransaction.Bucket.GENERAL


@pytest.fixture
def user(db):
    return User.objects.create_user("points@example.com", password="password")


@pytest.fixture
def other_user(db):
    return User.objects.create_user("other@example.com", password="password")


@pytest.fixture
def staff(db):
    return User.objects.create_user(
        "staff@example.com", password="password", is_staff=True
    )


@pytest.fixture
def account(user):
    return services.ensure_account(user)


def issue(account, amount, *, key=None, actor=None, bucket=BUCKET, reference="test"):
    return services.issue_points(
        account,
        amount,
        actor=actor,
        source_reference=reference,
        bucket=bucket,
        idempotency_key=key,
    )


# --- ensure_account -----------------------------------------------------------


def test_ensure_account_creates_exactly_one_account(db, user):
    first = services.ensure_account(user)
    second = services.ensure_account(user)
    assert first.pk == second.pk
    assert PointAccount.objects.filter(user=user).count() == 1


# --- issue_points -------------------------------------------------------------


def test_issue_points_credits_account_and_writes_ledger(account, staff):
    result = issue(account, 20, key="starter:1", actor=staff, reference="signup")
    assert result.created
    account.refresh_from_db()
    assert account.available == 20
    assert account.reserved == 0
    assert result.transaction.amount == 20
    assert result.transaction.type == PointTransaction.Type.ISSUE
    assert result.transaction.actor_id == staff.pk


def test_issue_points_can_be_a_system_call_without_actor(account):
    result = issue(account, 20, key="system:1")
    assert result.created
    assert result.transaction.actor is None


@pytest.mark.parametrize("amount", [0, -1, 1.5, True, "5"])
def test_issue_points_rejects_invalid_amounts(account, amount):
    with pytest.raises(ValueError):
        issue(account, amount, key="bad")
    assert PointTransaction.objects.count() == 0
    account.refresh_from_db()
    assert account.available == 0


@pytest.mark.parametrize("bucket", ["", "not-a-bucket", None])
def test_issue_points_rejects_unknown_bucket(account, bucket):
    with pytest.raises(ValueError):
        issue(account, 5, key="bucket", bucket=bucket)


def test_issue_points_requires_staff_actor(account, user):
    with pytest.raises(PermissionDenied):
        issue(account, 5, key="denied", actor=user)
    assert PointTransaction.objects.count() == 0


def test_repeated_issue_with_same_key_and_arguments_replays_prior_outcome(account):
    first = issue(account, 20, key="same")
    second = issue(account, 20, key="same")
    assert first.created
    assert not second.created
    assert first.transaction.pk == second.transaction.pk
    assert PointTransaction.objects.count() == 1
    account.refresh_from_db()
    assert account.available == 20


def test_reusing_a_key_with_different_arguments_raises(account):
    issue(account, 20, key="bound")
    with pytest.raises(IdempotencyConflictError):
        issue(account, 30, key="bound")
    account.refresh_from_db()
    assert account.available == 20
    assert PointTransaction.objects.count() == 1


# --- transfer -----------------------------------------------------------------


def test_transfer_writes_matched_entries(user, other_user):
    source = services.ensure_account(user)
    destination = services.ensure_account(other_user)
    issue(source, 50, key="fund")

    result = services.transfer(
        source,
        destination,
        20,
        actor=user,
        source_reference="transfer-1",
        bucket=BUCKET,
        idempotency_key="t1",
    )

    assert result.created
    assert result.debit.amount == -20
    assert result.credit.amount == 20
    assert result.debit.idempotency_key == result.credit.idempotency_key == "t1"
    assert result.debit.bucket == result.credit.bucket == BUCKET
    source.refresh_from_db()
    destination.refresh_from_db()
    assert source.available == 30
    assert destination.available == 20


def test_transfer_retry_replays_both_legs(user, other_user):
    source = services.ensure_account(user)
    destination = services.ensure_account(other_user)
    issue(source, 50, key="fund")
    first = services.transfer(
        source,
        destination,
        20,
        actor=user,
        source_reference="r",
        bucket=BUCKET,
        idempotency_key="retry",
    )
    second = services.transfer(
        source,
        destination,
        20,
        actor=user,
        source_reference="r",
        bucket=BUCKET,
        idempotency_key="retry",
    )
    assert first.created
    assert not second.created
    assert first.debit.pk == second.debit.pk
    assert first.credit.pk == second.credit.pk
    assert PointTransaction.objects.count() == 3


def test_transfer_rejects_self_transfer(account):
    issue(account, 10, key="fund")
    with pytest.raises(ValueError):
        services.transfer(
            account,
            account,
            5,
            actor=None,
            source_reference="self",
            bucket=BUCKET,
        )


def test_transfer_rejects_insufficient_balance(account, other_user):
    destination = services.ensure_account(other_user)
    with pytest.raises(InsufficientPointsError):
        services.transfer(
            account,
            destination,
            5,
            actor=None,
            source_reference="overdraft",
            bucket=BUCKET,
        )
    account.refresh_from_db()
    assert account.available == 0
    assert PointTransaction.objects.count() == 0


# --- reserve / capture / release ----------------------------------------------


def test_reserve_hold_then_capture_pays_recipient(user, other_user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="booking-1",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=other_user,
    )
    assert reserved.created
    learner.refresh_from_db()
    assert (learner.available, learner.reserved) == (30, 20)
    assert reserved.reservation.state == PointReservation.State.RESERVED

    captured = services.capture(reserved.reservation, actor=other_user)
    assert captured.created
    learner.refresh_from_db()
    teacher = services.ensure_account(other_user)
    assert (learner.available, learner.reserved) == (30, 0)
    assert teacher.available == 20
    assert captured.transaction.type == PointTransaction.Type.CAPTURE
    assert captured.reservation.state == PointReservation.State.CAPTURED
    assert captured.reservation.resolved_at is not None


def test_reserve_hold_then_release_returns_points(user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="booking-2",
        bucket=PointTransaction.Bucket.BOOKING,
    )
    released = services.release(reserved.reservation, actor=user)
    assert released.created
    learner.refresh_from_db()
    assert (learner.available, learner.reserved) == (50, 0)
    assert released.transaction.type == PointTransaction.Type.RELEASE
    assert released.reservation.state == PointReservation.State.RELEASED


def test_reserve_retry_without_a_key_is_idempotent(user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    kwargs = {
        "actor": user,
        "source_reference": "same-booking",
        "bucket": PointTransaction.Bucket.BOOKING,
    }
    first = services.reserve(learner, 20, **kwargs)
    second = services.reserve(learner, 20, **kwargs)
    assert first.created
    assert not second.created
    assert first.reservation.pk == second.reservation.pk
    assert PointReservation.objects.count() == 1
    learner.refresh_from_db()
    assert (learner.available, learner.reserved) == (30, 20)


def test_capture_retry_without_a_key_is_idempotent(user, other_user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="c",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=other_user,
    )
    first = services.capture(reserved.reservation, actor=other_user)
    second = services.capture(reserved.reservation, actor=other_user)
    assert first.created
    assert not second.created
    assert first.transaction.pk == second.transaction.pk
    teacher = services.ensure_account(other_user)
    assert teacher.available == 20
    assert (
        PointTransaction.objects.filter(type=PointTransaction.Type.CAPTURE).count() == 1
    )


def test_release_retry_without_a_key_is_idempotent(user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="rel",
        bucket=PointTransaction.Bucket.BOOKING,
    )
    first = services.release(reserved.reservation, actor=user)
    second = services.release(reserved.reservation, actor=user)
    assert first.created
    assert not second.created
    learner.refresh_from_db()
    assert learner.available == 50


def test_capture_requires_a_recipient(user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="no-recipient",
        bucket=PointTransaction.Bucket.BOOKING,
    )
    with pytest.raises(ValueError):
        services.capture(reserved.reservation, actor=user)


def test_capture_rejects_a_contradicting_recipient(user, other_user, staff):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="contradict",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=other_user,
    )
    with pytest.raises(ValueError):
        services.capture(reserved.reservation, actor=staff, recipient=staff)


def test_reserve_then_release_after_capture_raises(user, other_user):
    learner = services.ensure_account(user)
    issue(learner, 50, key="fund")
    reserved = services.reserve(
        learner,
        20,
        actor=user,
        source_reference="terminal",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=other_user,
    )
    services.capture(reserved.reservation, actor=other_user)
    with pytest.raises(ValueError):
        services.release(reserved.reservation, actor=user)


def test_reserve_rejects_insufficient_balance_and_leaves_no_trace(user):
    learner = services.ensure_account(user)
    with pytest.raises(InsufficientPointsError):
        services.reserve(
            learner,
            5,
            actor=user,
            source_reference="empty",
            bucket=PointTransaction.Bucket.BOOKING,
        )
    learner.refresh_from_db()
    assert (learner.available, learner.reserved) == (0, 0)
    assert PointReservation.objects.count() == 0
    assert PointTransaction.objects.count() == 0


# --- adjust -------------------------------------------------------------------


def test_adjust_requires_staff_a_reason_and_a_nonzero_amount(account, user):
    with pytest.raises(PermissionDenied):
        services.adjust(account, 5, actor=user, source_reference="x", reason="why")
    with pytest.raises(ValueError):
        services.adjust(account, 5, actor=None, source_reference="x", reason="  ")
    with pytest.raises(ValueError):
        services.adjust(account, 0, actor=None, source_reference="x", reason="why")
    assert PointTransaction.objects.count() == 0


def test_adjust_writes_a_compensating_entry(account):
    issue(account, 20, key="fund")
    result = services.adjust(
        account, -5, actor=None, source_reference="correction", reason="test fix"
    )
    assert result.created
    account.refresh_from_db()
    assert account.available == 15
    assert result.transaction.type == PointTransaction.Type.ADJUSTMENT
    assert result.transaction.amount == -5


def test_adjust_refuses_to_drive_available_negative(account):
    with pytest.raises(InsufficientPointsError):
        services.adjust(
            account, -1, actor=None, source_reference="x", reason="overcorrect"
        )


# --- reconciliation -----------------------------------------------------------


def corrupt_cache(account, *, available, reserved):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE points_pointaccount SET available = %s, reserved = %s "
            "WHERE id = %s",
            [available, reserved, account.pk],
        )


def test_reconcile_repairs_a_divergent_cache(account):
    issue(account, 10, key="fund")
    corrupt_cache(account, available=999, reserved=42)
    result = services.reconcile_account(account)
    assert result.repaired
    assert (
        result.before_available,
        result.before_reserved,
        result.after_available,
        result.after_reserved,
    ) == (999, 42, 10, 0)
    account.refresh_from_db()
    assert (account.available, account.reserved) == (10, 0)
    assert PointTransaction.objects.count() == 1


def test_reconcile_leaves_a_healthy_account_untouched(account):
    issue(account, 10, key="fund")
    result = services.reconcile_account(account)
    assert not result.repaired
    assert PointTransaction.objects.count() == 1


def test_cached_totals_always_match_the_ledger(account, other_user):
    destination = services.ensure_account(other_user)
    issue(account, 100, key="fund")
    services.transfer(
        account,
        destination,
        30,
        actor=None,
        source_reference="t",
        bucket=BUCKET,
    )
    reserved = services.reserve(
        destination,
        10,
        actor=None,
        source_reference="b",
        bucket=PointTransaction.Bucket.BOOKING,
    )
    services.release(reserved.reservation, actor=None)

    for current in (account, destination):
        current.refresh_from_db()
        expected_available = (
            current.transactions.aggregate(total=Sum("amount"))["total"] or 0
        )
        expected_reserved = (
            current.reservations.filter(
                state=PointReservation.State.RESERVED
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        assert current.available == expected_available
        assert current.reserved == expected_reserved
        assert current.available >= 0
        assert current.reserved >= 0


# --- append-only and cache protections ----------------------------------------


def test_ledger_entries_are_append_only(account):
    transaction_row = issue(account, 5, key="append").transaction
    with pytest.raises(ImmutableLedgerError):
        transaction_row.save()
    with pytest.raises(ImmutableLedgerError):
        PointTransaction.objects.filter(pk=transaction_row.pk).update(amount=1)
    with pytest.raises(ImmutableLedgerError):
        PointTransaction.objects.filter(pk=transaction_row.pk).delete()
    assert PointTransaction.objects.get(pk=transaction_row.pk).amount == 5


def test_cached_balances_cannot_be_updated_directly(account):
    with pytest.raises(ProtectedBalanceError):
        PointAccount.objects.filter(pk=account.pk).update(available=1)
    with pytest.raises(ProtectedBalanceError):
        PointAccount.objects.filter(pk=account.pk).update(reserved=1)


def test_points_package_has_no_ledger_update_or_delete_path():
    pattern = re.compile(r"\.update\(|\.delete\(")
    offenders = []
    for path in pathlib.Path("points").rglob("*.py"):
        if pattern.search(path.read_text()):
            offenders.append(str(path))
    assert offenders == [], f"append-only ledger mutated in {offenders}"


# --- admin --------------------------------------------------------------------


def test_admin_registers_accounts_and_ledger_read_only():
    account_admin = site._registry[PointAccount]
    ledger_admin = site._registry[PointTransaction]

    for admin_instance in (account_admin, ledger_admin):
        assert admin_instance.has_add_permission(None) is False
        assert admin_instance.has_change_permission(None) is False
        assert admin_instance.has_delete_permission(None) is False

    assert {"user", "available", "reserved", "updated_at"} <= set(
        account_admin.readonly_fields
    )
    assert {
        "account",
        "amount",
        "bucket",
        "type",
        "actor",
        "source_reference",
        "idempotency_key",
        "arguments_digest",
        "reason",
        "created_at",
    } <= set(ledger_admin.readonly_fields)


# --- no money ----------------------------------------------------------------


def test_points_app_has_no_price_currency_or_payment_path():
    banned = ("price", "currency", "payment", "cost", "paid")
    for model in (PointAccount, PointTransaction, PointReservation):
        field_names = {field.name for field in model._meta.get_fields()}
        assert not field_names & set(banned), (model, field_names & set(banned))


# --- PostgreSQL-only: locking, concurrency and rollback -----------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_produces_exactly_one_entry(user):
    require_postgres()
    account = services.ensure_account(user)
    start = threading.Barrier(6)
    results = [None] * 6
    errors = []

    def worker(index):
        connection.close()
        try:
            start.wait(timeout=10)
            local = PointAccount.objects.get(pk=account.pk)
            results[index] = issue(local, 5, key="race-key", reference="race")
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert PointTransaction.objects.filter(idempotency_key="race-key").count() == 1
    account.refresh_from_db()
    assert account.available == 5


@pytest.mark.django_db(transaction=True)
def test_opposite_order_transfers_do_not_deadlock(user, other_user):
    require_postgres()
    first = services.ensure_account(user)
    second = services.ensure_account(other_user)
    issue(first, 100, key="fund-a")
    issue(second, 100, key="fund-b")

    start = threading.Barrier(2)
    errors = []

    def worker(source_pk, destination_pk, reference):
        connection.close()
        try:
            start.wait(timeout=10)
            source = PointAccount.objects.get(pk=source_pk)
            destination = PointAccount.objects.get(pk=destination_pk)
            services.transfer(
                source,
                destination,
                10,
                actor=None,
                source_reference=reference,
                bucket=BUCKET,
            )
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=worker, args=(first.pk, second.pk, "a-to-b")),
        threading.Thread(target=worker, args=(second.pk, first.pk, "b-to-a")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.available, second.available) == (100, 100)
    assert first.available + second.available == 200


@pytest.mark.django_db
def test_lock_statement_is_ordered_by_user_id(user, other_user):
    require_postgres()
    first = services.ensure_account(user)
    second = services.ensure_account(other_user)
    issue(first, 50, key="fund")

    with CaptureQueriesContext(connection) as captured:
        services.transfer(
            first,
            second,
            10,
            actor=None,
            source_reference="lock-order",
            bucket=BUCKET,
        )

    lock_statements = [
        query["sql"]
        for query in captured.captured_queries
        if "FOR UPDATE" in query["sql"].upper()
    ]
    assert lock_statements, [q["sql"] for q in captured.captured_queries]
    statement = lock_statements[0].upper()
    assert "ORDER BY" in statement
    assert "USER_ID" in statement


@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_never_drive_balances_negative(user):
    require_postgres()
    account = services.ensure_account(user)
    issue(account, 100, key="fund")
    start = threading.Barrier(6)
    errors = []
    failures = []

    def worker(index):
        connection.close()
        try:
            start.wait(timeout=10)
            local = PointAccount.objects.get(pk=account.pk)
            services.reserve(
                local,
                30,
                actor=user,
                source_reference=f"spend-{index}",
                bucket=PointTransaction.Bucket.BOOKING,
            )
        except InsufficientPointsError:
            failures.append(index)
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    account.refresh_from_db()
    assert account.available >= 0
    assert account.reserved >= 0
    assert account.available + account.reserved == 100
    assert account.reserved == 90
    assert len(failures) == 3


@pytest.mark.django_db(transaction=True)
def test_injected_failure_rolls_back_the_whole_operation(user):
    require_postgres()
    account = services.ensure_account(user)
    issue(account, 10, key="fund")
    before = PointTransaction.objects.count()

    with patch("points.services._create_transaction", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            issue(account, 5, key="rollback")

    account.refresh_from_db()
    assert account.available == 10
    assert PointTransaction.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_points_are_conserved_across_transfer_capture_and_release(user, other_user):
    require_postgres()
    first = services.ensure_account(user)
    second = services.ensure_account(other_user)
    issue(first, 100, key="fund")

    services.transfer(
        first, second, 40, actor=None, source_reference="t", bucket=BUCKET
    )
    reservation = services.reserve(
        second,
        20,
        actor=None,
        source_reference="b",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=user,
    )
    services.capture(reservation.reservation, actor=user)
    released = services.reserve(
        second,
        10,
        actor=None,
        source_reference="b2",
        bucket=PointTransaction.Bucket.BOOKING,
    )
    services.release(released.reservation, actor=None)

    aggregate = PointAccount.objects.aggregate(
        total=Sum(F("available") + F("reserved"))
    )
    total = aggregate["total"] or 0
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.available + first.reserved + second.available + second.reserved == 100
    assert total == 100
