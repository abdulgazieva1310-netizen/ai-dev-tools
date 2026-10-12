"""Tests for the starter-point grant on verified accounts.

The concurrent-grant test relies on row locking, which only behaves like
production on PostgreSQL, so it uses ``require_postgres()``: when this file is
run explicitly against SQLite it fails via ``pytest.fail()`` instead of passing
for the wrong reason, and an implicit whole-suite SQLite run skips it.
"""

import importlib
import os
import sys
import threading
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from django.conf import settings
from django.core import signing
from django.db import connection
from django.db.models import Sum
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.email_verification import TOKEN_SALT
from accounts.models import ExternalIdentity, User
from accounts.oidc import GoogleOIDCBackend
from accounts.starter_points import grant_starter_points
from points import services
from points.models import PointAccount, PointTransaction


def require_postgres():
    """Guard for PostgreSQL-only assertions."""
    if connection.vendor == "postgresql":
        return
    if os.environ.get("RUN_POSTGRES_STARTER_TESTS") == "1" or any(
        argument.endswith("tests/test_starter_points.py") for argument in sys.argv
    ):
        pytest.fail(
            "Starter-grant row locking needs the Compose PostgreSQL database; "
            f"the configured backend is {connection.vendor}."
        )
    pytest.skip("PostgreSQL-only starter-grant tests run in Docker Compose.")


@pytest.fixture(autouse=True)
def google_settings(settings):
    settings.GOOGLE_OIDC_CLIENT_ID = "test-client-id"
    settings.GOOGLE_OIDC_CLIENT_SECRET = "test-client-secret-with-more-than-32-bytes"
    settings.OIDC_RP_CLIENT_ID = "test-client-id"
    settings.OIDC_RP_CLIENT_SECRET = "test-client-secret-with-more-than-32-bytes"
    settings.OIDC_RP_SIGN_ALGO = "HS256"
    settings.GOOGLE_OIDC_CALLBACK_URL = "http://testserver/oidc/callback/"
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://accounts.google.test/auth"


def verified_user(email="person@example.com"):
    return User.objects.create_user(
        email, "correct-horse", email_verified_at=timezone.now()
    )


def email_token(user):
    return signing.dumps(
        {"purpose": "verify-email", "user_id": user.pk, "email": user.email},
        salt=TOKEN_SALT,
    )


def start_google_flow(client):
    response = client.get(reverse("google_login"))
    params = parse_qs(urlsplit(response.url).query)
    state = params["state"][0]
    nonce = client.session["oidc_states"][state]["nonce"]
    return state, nonce


def provider_claims(nonce, **overrides):
    return {
        "sub": "google-subject-1",
        "email": "Person@example.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "exp": 4_102_444_800,
        "nonce": nonce,
        **overrides,
    }


def google_sign_in(client, monkeypatch, **overrides):
    state, nonce = start_google_flow(client)
    id_token = jwt.encode(
        provider_claims(nonce, **overrides),
        settings.OIDC_RP_CLIENT_SECRET,
        algorithm=settings.OIDC_RP_SIGN_ALGO,
    )
    monkeypatch.setattr(
        GoogleOIDCBackend,
        "get_token",
        lambda self, payload: {
            "id_token": id_token,
            "access_token": "mock-access-token",
        },
    )
    return client.get(reverse("oidc_callback"), {"state": state, "code": "mock-code"})


# --- configuration ------------------------------------------------------------


def test_starter_points_defaults_to_twenty_when_env_unset(monkeypatch):
    monkeypatch.delenv("STARTER_POINTS", raising=False)
    module = importlib.reload(importlib.import_module("config.settings"))
    assert module.STARTER_POINTS == 20


# --- trigger paths ------------------------------------------------------------


@pytest.mark.django_db
def test_email_verification_grants_starter_points(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = email_token(user)

    response = client.get(reverse("verify_email", kwargs={"token": token}))

    user.refresh_from_db()
    account = PointAccount.objects.get(user=user)
    assert response.status_code == 200
    assert user.email_verified_at is not None
    assert account.available == settings.STARTER_POINTS
    assert account.reserved == 0


@pytest.mark.django_db
def test_google_first_sign_in_grants_starter_points(client, monkeypatch):
    response = google_sign_in(client, monkeypatch)

    user = User.objects.get(email="person@example.com")
    account = PointAccount.objects.get(user=user)
    assert response.status_code == 302
    assert account.available == settings.STARTER_POINTS


@pytest.mark.django_db
def test_already_linked_verified_identity_grants_on_sign_in(client, monkeypatch):
    user = verified_user()
    ExternalIdentity.objects.create(
        user=user, provider="google", subject="google-subject-1"
    )

    response = google_sign_in(client, monkeypatch)

    account = PointAccount.objects.get(user=user)
    assert response.status_code == 302
    assert account.available == settings.STARTER_POINTS
    assert PointAccount.objects.filter(user=user).count() == 1


# --- eligibility --------------------------------------------------------------


@pytest.mark.django_db
def test_unverified_active_user_grants_nothing():
    user = User.objects.create_user("person@example.com", "correct-horse")

    assert grant_starter_points(user) is None
    assert not PointAccount.objects.filter(user=user).exists()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [User.State.SUSPENDED, User.State.DELETION_PENDING, User.State.DELETED],
)
def test_inactive_state_grants_nothing(state):
    user = verified_user()
    user.state = state
    user.save(update_fields=["state"])

    assert grant_starter_points(user) is None
    assert not PointAccount.objects.filter(user=user).exists()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
def test_unverified_linked_google_identity_grants_nothing(client, monkeypatch):
    user = User.objects.create_user("person@example.com", password=None)
    ExternalIdentity.objects.create(
        user=user, provider="google", subject="google-subject-1"
    )

    response = google_sign_in(client, monkeypatch)

    assert response.status_code == 302
    assert not PointAccount.objects.filter(user=user).exists()


# --- amount handling ----------------------------------------------------------


@pytest.mark.django_db
@override_settings(STARTER_POINTS=0)
def test_zero_starter_points_writes_nothing():
    user = verified_user()

    assert grant_starter_points(user) is None
    assert not PointAccount.objects.filter(user=user).exists()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
@override_settings(STARTER_POINTS=0)
def test_zero_starter_points_keeps_existing_balance():
    user = verified_user()
    account = services.ensure_account(user)
    services.issue_points(
        account,
        7,
        actor=None,
        source_reference="seed",
        bucket="general",
        idempotency_key="seed",
    )

    assert grant_starter_points(user) is None

    account.refresh_from_db()
    assert account.available == 7


@pytest.mark.django_db
@override_settings(STARTER_POINTS=0)
def test_email_verification_succeeds_with_zero_starter_points(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = email_token(user)

    response = client.get(reverse("verify_email", kwargs={"token": token}))

    user.refresh_from_db()
    assert response.status_code == 200
    assert user.email_verified_at is not None
    assert not PointAccount.objects.filter(user=user).exists()


@pytest.mark.django_db
@override_settings(STARTER_POINTS=-5)
def test_negative_starter_points_writes_nothing():
    user = verified_user()

    assert grant_starter_points(user) is None
    assert not PointAccount.objects.filter(user=user).exists()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
@override_settings(STARTER_POINTS=-5)
def test_negative_starter_points_keeps_existing_balance():
    user = verified_user()
    account = services.ensure_account(user)
    services.issue_points(
        account,
        7,
        actor=None,
        source_reference="seed",
        bucket="general",
        idempotency_key="seed",
    )

    assert grant_starter_points(user) is None

    account.refresh_from_db()
    assert account.available == 7


@pytest.mark.django_db
def test_failed_grant_rolls_back_email_verification_and_link_can_be_retried(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = email_token(user)
    url = reverse("verify_email", kwargs={"token": token})
    client.raise_request_exception = False

    with patch("points.services._create_transaction", side_effect=RuntimeError("boom")):
        first = client.get(url)

    assert first.status_code == 500
    user.refresh_from_db()
    assert user.email_verified_at is None
    assert not PointAccount.objects.filter(user=user).exists()
    assert PointTransaction.objects.count() == 0

    second = client.get(url)

    assert second.status_code == 200
    user.refresh_from_db()
    account = PointAccount.objects.get(user=user)
    assert user.email_verified_at is not None
    assert account.available == settings.STARTER_POINTS


# --- pre-existing account and idempotency -------------------------------------


@pytest.mark.django_db
def test_pre_existing_account_is_credited_not_recreated():
    user = verified_user()
    account = services.ensure_account(user)
    services.issue_points(
        account,
        5,
        actor=None,
        source_reference="seed",
        bucket="general",
        idempotency_key="seed",
    )

    result = grant_starter_points(user)

    account.refresh_from_db()
    assert result.created
    assert account.available == 5 + settings.STARTER_POINTS
    assert PointAccount.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_repeated_grant_returns_created_false():
    user = verified_user()

    first = grant_starter_points(user)
    second = grant_starter_points(user)

    account = PointAccount.objects.get(user=user)
    assert first.created
    assert second.created is False
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    assert account.available == settings.STARTER_POINTS


@pytest.mark.django_db
def test_repeat_grant_after_amount_change_returns_created_false():
    user = verified_user()

    with override_settings(STARTER_POINTS=20):
        first = grant_starter_points(user)
    assert first.created
    assert first.transaction.amount == 20

    with override_settings(STARTER_POINTS=30):
        second = grant_starter_points(user)

    account = PointAccount.objects.get(user=user)
    assert second.created is False
    assert second.transaction.pk == first.transaction.pk
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    assert account.available == 20


@pytest.mark.django_db
def test_replayed_email_token_grants_once(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = email_token(user)

    first = client.get(reverse("verify_email", kwargs={"token": token}))
    second = client.get(reverse("verify_email", kwargs={"token": token}))

    account = PointAccount.objects.get(user=user)
    assert first.status_code == 200
    assert second.status_code == 400
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    assert account.available == settings.STARTER_POINTS


@pytest.mark.django_db
def test_repeated_google_callback_grants_once(client, monkeypatch):
    assert google_sign_in(client, monkeypatch).status_code == 302
    assert google_sign_in(client, monkeypatch).status_code == 302

    user = User.objects.get(email="person@example.com")
    account = PointAccount.objects.get(user=user)
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    assert account.available == settings.STARTER_POINTS


@pytest.mark.django_db
def test_repeated_google_callback_with_changed_amount_signs_in(client, monkeypatch):
    with override_settings(STARTER_POINTS=20):
        first = google_sign_in(client, monkeypatch)
    assert first.status_code == 302

    user = User.objects.get(email="person@example.com")
    assert PointAccount.objects.get(user=user).available == 20

    with override_settings(STARTER_POINTS=30):
        second = google_sign_in(client, monkeypatch)

    user.refresh_from_db()
    account = PointAccount.objects.get(user=user)
    assert second.status_code == 302
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    assert account.available == 20


# --- ledger shape and agreement -----------------------------------------------


@pytest.mark.django_db
def test_ledger_entry_uses_system_starter_key():
    user = verified_user()

    entry = grant_starter_points(user).transaction

    assert entry.type == PointTransaction.Type.ISSUE
    assert entry.bucket == PointTransaction.Bucket.STARTER
    assert entry.actor is None
    assert entry.source_reference == f"user:{user.pk}"
    assert entry.idempotency_key == f"starter:{user.pk}"


@pytest.mark.django_db
def test_balance_reconciles_with_the_ledger():
    user = verified_user()

    account = grant_starter_points(user).account
    account.refresh_from_db()
    ledger_total = account.transactions.aggregate(total=Sum("amount"))["total"]

    assert account.available == settings.STARTER_POINTS
    assert ledger_total == account.available
    assert services.reconcile_account(account).repaired is False


@pytest.mark.django_db
def test_only_intended_account_and_ledger_rows_change_after_repeat():
    target = verified_user("target@example.com")
    bystander = verified_user("bystander@example.com")

    with override_settings(STARTER_POINTS=20):
        grant_starter_points(target)
        grant_starter_points(target)

    assert PointAccount.objects.count() == 1
    assert PointTransaction.objects.count() == 1
    entry = PointTransaction.objects.get()
    account = PointAccount.objects.get(user=target)
    assert entry.idempotency_key == f"starter:{target.pk}"
    assert entry.account == account
    assert account.available == 20
    assert account.reserved == 0
    assert not PointAccount.objects.filter(user=bystander).exists()


# --- PostgreSQL-only: concurrency ---------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_grants_produce_exactly_one_entry():
    require_postgres()
    user = verified_user("race@example.com")

    start = threading.Barrier(6)
    results = [None] * 6
    errors = []

    def worker(index):
        connection.close()
        try:
            start.wait(timeout=10)
            local = User.objects.get(pk=user.pk)
            results[index] = grant_starter_points(local)
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
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    account = PointAccount.objects.get(user=user)
    assert account.available == settings.STARTER_POINTS
    assert sum(1 for result in results if result and result.created) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_email_callbacks_produce_exactly_one_entry():
    require_postgres()
    user = User.objects.create_user("race2@example.com", "correct-horse")
    token = email_token(user)
    url = reverse("verify_email", kwargs={"token": token})

    start = threading.Barrier(6)
    statuses = [None] * 6
    errors = []

    def worker(index):
        connection.close()
        try:
            start.wait(timeout=10)
            statuses[index] = Client().get(url).status_code
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
    assert all(status in (200, 400) for status in statuses), statuses
    assert statuses.count(200) == 1, statuses
    assert (
        PointTransaction.objects.filter(idempotency_key=f"starter:{user.pk}").count()
        == 1
    )
    account = PointAccount.objects.get(user=user)
    assert account.available == settings.STARTER_POINTS
    assert account.reserved == 0
