import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from accounts.models import ExternalIdentity, User
from accounts.oidc import GoogleOIDCBackend


def start_google_flow(client):
    response = client.get(reverse("google_login"))
    authorization_url = urlsplit(response.url)
    params = parse_qs(authorization_url.query)
    state = params["state"][0]
    session = client.session
    nonce = session["oidc_states"][state]["nonce"]
    return state, nonce, params


def mock_google_provider(monkeypatch, claims):
    id_token = jwt.encode(
        claims,
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


@pytest.fixture(autouse=True)
def google_settings(settings):
    settings.GOOGLE_OIDC_CLIENT_ID = "test-client-id"
    settings.GOOGLE_OIDC_CLIENT_SECRET = "test-client-secret-with-more-than-32-bytes"
    settings.OIDC_RP_CLIENT_ID = "test-client-id"
    settings.OIDC_RP_CLIENT_SECRET = "test-client-secret-with-more-than-32-bytes"
    settings.OIDC_RP_SIGN_ALGO = "HS256"
    settings.GOOGLE_OIDC_CALLBACK_URL = "http://testserver/oidc/callback/"
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://accounts.google.test/auth"


@pytest.mark.django_db
def test_google_first_sign_in_creates_verified_account_and_stable_identity(
    client, monkeypatch
):
    state, nonce, params = start_google_flow(client)
    claims = provider_claims(nonce)
    mock_google_provider(monkeypatch, claims)

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 302
    user = User.objects.get(email="person@example.com")
    identity = ExternalIdentity.objects.get(provider="google", subject=claims["sub"])
    assert identity.user == user
    assert user.email_verified_at is not None
    assert user.has_usable_password() is False
    assert params["nonce"] == [nonce]
    assert params["redirect_uri"] == ["http://testserver/oidc/callback/"]
    assert "oidc_access_token" not in client.session
    assert "oidc_id_token" not in client.session
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_repeat_google_sign_in_resolves_same_account(client, monkeypatch):
    user = User.objects.create_user(
        "person@example.com", password=None, email_verified_at=None
    )
    ExternalIdentity.objects.create(
        user=user, provider="google", subject="google-subject-1"
    )
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(monkeypatch, provider_claims(nonce))

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 302
    assert User.objects.count() == 1
    assert ExternalIdentity.objects.count() == 1
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_provider_error_does_not_authenticate_or_log_out_existing_user(client):
    user = User.objects.create_user("person@example.com", "secret-password")
    client.force_login(user)

    response = client.get(reverse("oidc_callback"), {"error": "access_denied"})

    assert response.status_code == 400
    assert client.session.get("_auth_user_id") == str(user.pk)


def test_google_login_is_unavailable_without_credentials(client, settings):
    settings.GOOGLE_OIDC_CLIENT_SECRET = ""

    response = client.get(reverse("google_login"))

    assert response.status_code == 503
    assert "accounts.google.test" not in response.content.decode()


@pytest.mark.django_db
def test_callback_rejects_invalid_state(client, monkeypatch):
    monkeypatch.setattr(
        GoogleOIDCBackend,
        "get_token",
        lambda self, payload: pytest.fail("invalid state must not exchange code"),
    )

    response = client.get(
        reverse("oidc_callback"), {"state": "attacker-state", "code": "mock-code"}
    )

    assert response.status_code == 400
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_callback_rejects_missing_state_without_exchanging_code(client, monkeypatch):
    start_google_flow(client)
    monkeypatch.setattr(
        GoogleOIDCBackend,
        "get_token",
        lambda self, payload: pytest.fail("missing state must not exchange code"),
    )

    response = client.get(reverse("oidc_callback"), {"code": "mock-code"})

    assert response.status_code == 400
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_callback_rejects_expired_state_without_exchanging_code(client, monkeypatch):
    state, _, _ = start_google_flow(client)
    session = client.session
    session["oidc_states"][state]["added_on"] = time.time() - 601
    session.save()
    monkeypatch.setattr(
        GoogleOIDCBackend,
        "get_token",
        lambda self, payload: pytest.fail("expired state must not exchange code"),
    )

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert "_auth_user_id" not in client.session
    assert state not in client.session["oidc_states"]


@pytest.mark.django_db
def test_callback_rejects_invalid_nonce(client, monkeypatch):
    state, nonce, _ = start_google_flow(client)
    claims = provider_claims("wrong-nonce")
    mock_google_provider(monkeypatch, claims)

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert User.objects.count() == 0
    assert "_auth_user_id" not in client.session
    assert nonce != claims["nonce"]


@pytest.mark.django_db
def test_callback_rejects_invalid_id_token_signature(client, monkeypatch):
    state, _, _ = start_google_flow(client)
    monkeypatch.setattr(
        GoogleOIDCBackend,
        "get_token",
        lambda self, payload: {
            "id_token": "invalid.signature.token",
            "access_token": "untrusted-access-token",
        },
    )

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_google_identity_requires_verified_email(client, monkeypatch):
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(monkeypatch, provider_claims(nonce, email_verified=False))

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example"},
        {"aud": "some-other-client"},
        {"exp": 1},
    ],
)
@pytest.mark.django_db
def test_google_identity_rejects_invalid_issuer_audience_or_expiry(
    client, monkeypatch, claims
):
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(monkeypatch, provider_claims(nonce, **claims))

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert User.objects.count() == 0
    assert ExternalIdentity.objects.count() == 0


@pytest.mark.django_db
def test_google_email_match_does_not_automatically_link(client, monkeypatch):
    user = User.objects.create_user("person@example.com", "secret-password")
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(monkeypatch, provider_claims(nonce))

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert ExternalIdentity.objects.count() == 0
    assert User.objects.get(pk=user.pk) == user
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state_value",
    [User.State.SUSPENDED, User.State.DELETION_PENDING, User.State.DELETED],
)
def test_inactive_google_account_cannot_authenticate(client, monkeypatch, state_value):
    user = User.objects.create_user(
        "person@example.com", password=None, state=state_value
    )
    ExternalIdentity.objects.create(
        user=user, provider="google", subject="google-subject-1"
    )
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(monkeypatch, provider_claims(nonce))

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_explicit_linking_attaches_google_identity_to_authenticated_user(
    client, monkeypatch
):
    user = User.objects.create_user("person@example.com", "secret-password")
    client.force_login(user)
    response = client.get(reverse("google_link"))
    assert response.status_code == 302
    assert response.url == reverse("google_login")

    state, nonce, _ = start_google_flow(client)
    mock_google_provider(
        monkeypatch, provider_claims(nonce, email="different@example.com")
    )
    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 302
    identity = ExternalIdentity.objects.get(provider="google")
    assert identity.user == user
    assert User.objects.count() == 1
    assert client.session["_auth_user_id"] == str(user.pk)
    assert "google_link_user_id" not in client.session


@pytest.mark.django_db
def test_google_link_requires_authentication(client):
    response = client.get(reverse("google_link"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("login"))
    assert "google_link_user_id" not in client.session


@pytest.mark.django_db
def test_linking_rejects_identity_already_attached_to_another_account(
    client, monkeypatch
):
    user = User.objects.create_user("person@example.com", "secret-password")
    other = User.objects.create_user("other@example.com", "secret-password")
    ExternalIdentity.objects.create(
        user=other, provider="google", subject="google-subject-1"
    )
    client.force_login(user)
    client.get(reverse("google_link"))
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(
        monkeypatch, provider_claims(nonce, email="different@example.com")
    )

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert ExternalIdentity.objects.get(provider="google").user == other
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_linking_rejects_email_already_owned_by_another_account(client, monkeypatch):
    user = User.objects.create_user("person@example.com", "secret-password")
    email_owner = User.objects.create_user("different@example.com", "secret-password")
    client.force_login(user)
    client.get(reverse("google_link"))
    state, nonce, _ = start_google_flow(client)
    mock_google_provider(
        monkeypatch, provider_claims(nonce, email="different@example.com")
    )

    response = client.get(
        reverse("oidc_callback"), {"state": state, "code": "mock-code"}
    )

    assert response.status_code == 400
    assert ExternalIdentity.objects.count() == 0
    assert User.objects.get(pk=email_owner.pk) == email_owner
    assert client.session["_auth_user_id"] == str(user.pk)
