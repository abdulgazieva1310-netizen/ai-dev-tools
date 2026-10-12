# Points

Points are an internal, non-monetary credit. There is **no price, currency or
payment** anywhere in the app: `points/` stores whole, signed integers only, and
the admin never lets a human edit them. Every balance change goes through a
ledger entry, and the cached totals on the account are a derived value that
`reconcile_account()` can always rebuild from the ledger.

## The three models

| Model | Role |
| --- | --- |
| `PointAccount` | One row per user (`OneToOne`). Cached `available` and `reserved` totals. |
| `PointTransaction` | Append-only ledger. One signed `amount` row per balance movement. |
| `PointReservation` | A hold placed by `reserve()`, later `captured` or `released`. |

`PointAccount.available + PointAccount.reserved` is the account's total balance.
A reserve moves points from `available` to `reserved`; a capture moves the
reserved points to the recipient's `available`; a release moves them back.

### Append-only, cached totals only

- `PointTransaction` can be inserted but never changed or removed. Saving an
  existing row, and the queryset `.update()` / `.delete()` helpers, raise
  `ImmutableLedgerError`.
- `PointAccount` balances cannot be written directly: `PointAccount.objects.filter(...).update(...)`
  raises `ProtectedBalanceError`. Services write them with
  `save(update_fields=[...])` **after** locking the row.
- Both models enforce this with database `CheckConstraint`s as well (amounts are
  non-zero, cached totals are non-negative, reservation amount is positive).

## Service API

`points.services` is the only supported way to move points. Every function runs
inside `transaction.atomic()` and locks every account it touches with
`select_for_update()` in ascending `user_id` order, so two operations that share
an account cannot deadlock. Each returns a `NamedTuple` carrying the affected
rows plus a `created` flag.

```python
from points import services

account = services.ensure_account(user)  # idempotent

services.issue_points(
    account,
    20,
    actor=None,  # system grant
    source_reference="signup",
    bucket="starter",
    idempotency_key="signup:1",
)

services.transfer(
    source,
    destination,
    20,
    actor=user,
    source_reference="order-1",
    bucket="general",
    idempotency_key="order-1",
)

hold = services.reserve(
    account,
    20,
    actor=user,  # holds 20 points
    source_reference="booking-7",
    bucket="booking",
    recipient=teacher,
)
services.capture(hold.reservation, actor=teacher)  # pay the teacher
services.release(hold.reservation, actor=user)  # or give them back

services.adjust(
    account,
    -5,
    actor=staff,  # staff correction
    source_reference="ticket-3",
    reason="test fix",
)
services.reconcile_account(account)  # rebuild the cache
```

| Function | Effect | Actor rule |
| --- | --- | --- |
| `ensure_account(user)` | Create-or-get the account and lock it. | any |
| `issue_points(account, amount, ...)` | Credit `amount`. | staff, or `None` for a system call |
| `transfer(from, to, amount, ...)` | Move points between two accounts (matched debit/credit rows). | any |
| `reserve(account, amount, ...)` | Move `amount` from `available` to `reserved`, opening a reservation. | any |
| `capture(reservation, ...)` | Move the hold to the recipient's `available`. | any |
| `release(reservation, ...)` | Return the hold to the payer's `available`. | any |
| `adjust(account, amount, ...)` | Signed compensating entry; `reason` is required. | staff, or `None` |
| `reconcile_account(account)` | Rebuild cached totals from the ledger; never writes an entry. | any |

Amounts are validated strictly: `issue`/`transfer`/`reserve` require a positive
`int`, `adjust` requires a non-zero `int`, and a `bool` is rejected even though
it is an `int` subclass. `bucket` must be one of the `PointTransaction.Bucket`
values. Insufficient `available` raises `InsufficientPointsError`, which leaves
no ledger entry, no reservation and no cache change because the whole atomic
block rolls back.

## Idempotency

Pass `idempotency_key` to make a call safe to retry. The ledger stores the
SHA-256 of the operation arguments (`arguments_digest`) next to the key:

- same key **and** same arguments: the earlier result is returned with
  `created=False`, and nothing new is written;
- same key but **different** arguments: `IdempotencyConflictError` is raised.

`transfer` and `issue_points` write the digest on their row. `reserve` derives a
key (`reserve:<sha256-40>`) when none is given, and `capture` / `release` derive
`<ledger_key>:capture` and `<ledger_key>:release`, so a retried capture or
release cannot apply twice. The `(account, idempotency_key)` pair is unique in
the database, so a genuine race still cannot create a duplicate.

## Reconciliation

`reconcile_account(account)` recomputes `available` as the sum of every ledger
`amount` and `reserved` as the sum of all still-`reserved` reservations, then
writes them back only if they differ. It repairs the *cache*, never ownership:
to move points between users use `transfer`, and to correct a credit use
`adjust`, which leaves an audit trail.

## Admin

`PointAccount` and `PointTransaction` are registered read-only: `has_add`,
`has_change` and `has_delete` all return `False`, and every field is in
`readonly_fields`. Operators can inspect the ledger, but balances move only
through `points.services`.

## Tests

```bash
uv run pytest                                      # SQLite: everything but the
                                                   # PostgreSQL-only point tests
docker compose exec web pytest tests/test_points.py   # PostgreSQL
```

Row locking, concurrent operations and whole-transaction rollback only behave
like production on PostgreSQL. Those tests call `require_postgres()`: run this
file explicitly against SQLite and they `pytest.fail()`; run the whole suite on
SQLite and they are skipped. A test also scans `points/` to confirm no
`.update(` or `.delete(` path exists on the ledger.
