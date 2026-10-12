from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import mail, signing
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.email_verification import TOKEN_SALT
from accounts.models import User
from accounts.views import email_verified_required


@pytest.mark.django_db
def test_active_unverified_user_can_log_in(client):
    User.objects.create_user("person@example.com", "correct-horse")

    response = client.post(
        reverse("login"),
        {"username": "PERSON@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 302
    assert response.url == reverse("home")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [User.State.SUSPENDED, User.State.DELETION_PENDING, User.State.DELETED],
)
def test_non_active_users_cannot_log_in(client, state):
    User.objects.create_user("person@example.com", "correct-horse", state=state)

    response = client.post(
        reverse("login"),
        {"username": "person@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 200
    assert b"Email or password is incorrect." in response.content
    assert b"This account is inactive" not in response.content


@pytest.mark.django_db
def test_registration_creates_normalized_user_with_hashed_password(client):
    response = client.post(
        reverse("register"),
        {
            "email": " Person@Example.COM ",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("login")
    user = User.objects.get(email="person@example.com")
    assert user.check_password("correct-horse-and-battery-staple")


@pytest.mark.django_db
def test_registration_shows_normalized_duplicate_email_error(client):
    User.objects.create_user("person@example.com", "correct-horse")

    response = client.post(
        reverse("register"),
        {
            "email": " Person@Example.COM ",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
    )

    assert response.status_code == 200
    assert b"An account with this email already exists." in response.content
    assert User.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("password1", "password2"),
    [("correct-horse", "different-password"), ("12345", "12345")],
)
def test_registration_validates_passwords(client, password1, password2):
    response = client.post(
        reverse("register"),
        {"email": "person@example.com", "password1": password1, "password2": password2},
    )

    assert response.status_code == 200
    assert User.objects.count() == 0
    assert response.context["form"].errors


@pytest.mark.django_db
@pytest.mark.parametrize(
    "form_data",
    [
        {
            "email": "not-an-email",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
        {"email": "person@example.com", "password1": "", "password2": ""},
    ],
    ids=["malformed-email", "blank-password"],
)
def test_registration_rejects_malformed_email_and_blank_password(client, form_data):
    response = client.post(reverse("register"), form_data)

    assert response.status_code == 200
    assert response.context["form"].errors
    assert User.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("email", "password"),
    [("missing@example.com", "wrong"), ("person@example.com", "wrong")],
)
def test_login_errors_do_not_disclose_account_existence(client, email, password):
    User.objects.get_or_create(
        email="person@example.com", defaults={"password": "unused"}
    )

    response = client.post(reverse("login"), {"username": email, "password": password})

    assert response.status_code == 200
    assert b"Email or password is incorrect." in response.content
    assert b"does not exist" not in response.content


@pytest.mark.django_db
@pytest.mark.parametrize("email", ["person@example.com", "missing@example.com"])
def test_password_reset_request_is_non_enumerating(client, email):
    if not User.objects.filter(email="person@example.com").exists():
        User.objects.create_user("person@example.com", "correct-horse")

    response = client.post(reverse("password_reset"), {"email": email})

    assert response.status_code == 302
    assert response.url == reverse("password_reset_done")
    assert b"If an account matches" in client.get(response.url).content


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_does_not_send_email_to_inactive_user(client):
    User.objects.create_user(
        "person@example.com", "correct-horse", state=User.State.SUSPENDED
    )

    response = client.post(reverse("password_reset"), {"email": "person@example.com"})

    assert response.status_code == 302
    assert len(mail.outbox) == 0


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_delivers_email_and_uses_django_timeout(client):
    user = User.objects.create_user("person@example.com", "correct-horse")

    response = client.post(reverse("password_reset"), {"email": "person@example.com"})

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    token = default_token_generator.make_token(user)
    assert token in mail.outbox[0].body
    assert settings.PASSWORD_RESET_TIMEOUT == 259200


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_link_changes_password(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    client.post(reverse("password_reset"), {"email": user.email})
    reset_url = mail.outbox[0].body.split("\n")[2]
    path = urlsplit(reset_url).path
    reset_form = client.get(path, follow=True)
    assert reset_form.status_code == 200
    assert b"Choose a new password" in reset_form.content
    post_path = reset_form.request["PATH_INFO"]
    if reset_form.request["QUERY_STRING"]:
        post_path += "?" + reset_form.request["QUERY_STRING"]

    response = client.post(
        post_path,
        {"new_password1": "new-correct-horse", "new_password2": "new-correct-horse"},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password("new-correct-horse")


@pytest.mark.django_db
def test_password_reset_token_expires_after_builtin_timeout(monkeypatch):
    user = User.objects.create_user("person@example.com", "correct-horse")
    expired_time = default_token_generator._now() + timedelta(
        seconds=settings.PASSWORD_RESET_TIMEOUT + 1
    )
    token = default_token_generator.make_token(user)

    monkeypatch.setattr(default_token_generator, "_now", lambda: expired_time)
    assert not default_token_generator.check_token(user, token)


@pytest.mark.django_db
def test_logout_requires_post_and_clears_session(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    client.force_login(user)

    get_response = client.get(reverse("logout"))
    assert get_response.status_code == 405
    assert "_auth_user_id" in client.session

    post_response = client.post(reverse("logout"))
    assert post_response.status_code == 302
    assert post_response.url == reverse("login")
    assert "_auth_user_id" not in client.session


def test_auth_forms_include_csrf_tokens():
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    for url in (reverse("register"), reverse("login"), reverse("password_reset")):
        response = client.get(url)
        assert response.status_code == 200
        assert b"csrfmiddlewaretoken" in response.content
        assert client.cookies.get("csrftoken")


@pytest.mark.django_db
def test_registration_login_and_password_reset_post_require_csrf_token():
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    for url in (reverse("register"), reverse("login"), reverse("password_reset")):
        assert client.post(url, {}).status_code == 403


@pytest.mark.django_db
def test_logout_and_password_reset_confirmation_require_csrf_token():
    from django.test import Client

    user = User.objects.create_user("person@example.com", "correct-horse")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    assert client.post(reverse("logout")).status_code == 403
    reset_url = reverse(
        "password_reset_confirm",
        kwargs={"uidb64": "MQ", "token": "invalid-token"},
    )
    assert client.post(reset_url, {}).status_code == 403


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_registration_sends_signed_verification_email_and_stays_unverified(client):
    response = client.post(
        reverse("register"),
        {
            "email": "person@example.com",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
    )

    user = User.objects.get(email="person@example.com")
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert "Verify your SkillSwap email address" in mail.outbox[0].body
    verification_link = next(
        line for line in mail.outbox[0].body.splitlines() if "/verify-email/" in line
    )
    verification_path = urlsplit(verification_link).path
    token = verification_path.rstrip("/").rsplit("/", 1)[-1]
    assert signing.loads(
        token, salt=TOKEN_SALT, max_age=settings.EMAIL_VERIFICATION_TIMEOUT
    ) == {"purpose": "verify-email", "user_id": user.pk, "email": user.email}
    assert settings.EMAIL_VERIFICATION_TIMEOUT == 86400
    assert user.email_verified_at is None

    other_user = User.objects.create_user("other@example.com", "correct-horse")
    verify_response = client.get(verification_path)
    user.refresh_from_db()
    other_user.refresh_from_db()
    assert verify_response.status_code == 200
    assert user.email_verified_at is not None
    assert other_user.email_verified_at is None


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_verification_link_verifies_only_its_account_and_cannot_be_replayed(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    other_user = User.objects.create_user("other@example.com", "correct-horse")
    payload = {"purpose": "verify-email", "user_id": user.pk, "email": user.email}
    token = signing.dumps(payload, salt=TOKEN_SALT)

    response = client.get(reverse("verify_email", kwargs={"token": token}))
    user.refresh_from_db()
    other_user.refresh_from_db()
    assert response.status_code == 200
    assert user.email_verified_at is not None
    assert other_user.email_verified_at is None

    replay = client.get(reverse("verify_email", kwargs={"token": token}))
    assert replay.status_code == 400
    assert b"invalid, expired, or has already been used" in replay.content


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_VERIFICATION_TIMEOUT=7200,
)
def test_verification_link_works_with_positive_configured_timeout(client):
    response = client.post(
        reverse("register"),
        {
            "email": "person@example.com",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(email="person@example.com")
    verification_link = next(
        line for line in mail.outbox[0].body.splitlines() if "/verify-email/" in line
    )
    verification_path = urlsplit(verification_link).path
    token = verification_path.rstrip("/").rsplit("/", 1)[-1]
    assert signing.loads(token, salt=TOKEN_SALT, max_age=7200)["user_id"] == user.pk

    response = client.get(verification_path)

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email_verified_at is not None


@pytest.mark.django_db
@override_settings(EMAIL_VERIFICATION_TIMEOUT=-1)
def test_expired_verification_link_has_generic_failure(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = signing.dumps(
        {"purpose": "verify-email", "user_id": user.pk, "email": user.email},
        salt=TOKEN_SALT,
    )

    response = client.get(reverse("verify_email", kwargs={"token": token}))

    assert response.status_code == 400
    assert b"invalid, expired, or has already been used" in response.content
    user.refresh_from_db()
    assert user.email_verified_at is None


@pytest.mark.django_db
def test_invalid_purpose_verification_link_fails_generically(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    token = signing.dumps(
        {"purpose": "password-reset", "user_id": user.pk, "email": user.email},
        salt=TOKEN_SALT,
    )

    response = client.get(reverse("verify_email", kwargs={"token": token}))

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.email_verified_at is None


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_resend_verification_only_sends_to_authenticated_users_own_address(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    client.force_login(user)

    response = client.post(
        reverse("resend_verification"), {"email": "other@example.com"}
    )
    assert response.status_code == 302
    assert response.url == reverse("verification_resend_done")
    assert len(mail.outbox) == 0

    response = client.post(
        reverse("resend_verification"), {"email": "PERSON@example.com"}
    )
    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_verified_user_cannot_trigger_another_verification_email(client):
    user = User.objects.create_user("person@example.com", "correct-horse")
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    client.force_login(user)

    response = client.post(reverse("resend_verification"), {"email": user.email})

    assert response.status_code == 302
    assert response.url == reverse("verification_resend_done")
    assert len(mail.outbox) == 0


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_verification_delivery_failure_keeps_account_unverified(client, monkeypatch):
    def fail_send(*args, **kwargs):
        raise OSError("mail server unavailable")

    monkeypatch.setattr("accounts.views.send_verification_email", fail_send)
    response = client.post(
        reverse("register"),
        {
            "email": "person@example.com",
            "password1": "correct-horse-and-battery-staple",
            "password2": "correct-horse-and-battery-staple",
        },
    )

    user = User.objects.get(email="person@example.com")
    assert response.status_code == 503
    assert b"account was created" in response.content
    assert user.email_verified_at is None

    client.force_login(user)
    monkeypatch.undo()
    resend_response = client.post(
        reverse("resend_verification"), {"email": user.email.upper()}
    )

    assert resend_response.status_code == 302
    assert resend_response.url == reverse("verification_resend_done")
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    verification_link = next(
        line for line in mail.outbox[0].body.splitlines() if "/verify-email/" in line
    )
    token = urlsplit(verification_link).path.rstrip("/").rsplit("/", 1)[-1]
    assert signing.loads(token, salt=TOKEN_SALT)["user_id"] == user.pk


@pytest.mark.django_db
def test_email_verified_gate_redirects_unverified_users_and_allows_verified_users():
    request_factory = RequestFactory()
    guarded_view = email_verified_required(lambda request: HttpResponse("ok"))
    user = User.objects.create_user("person@example.com", "correct-horse")
    request = request_factory.get("/protected/")
    request.user = user

    response = guarded_view(request)
    assert response.status_code == 302
    assert response.url == reverse("email_verification_required")

    user.email_verified_at = timezone.now()
    request.user = user
    response = guarded_view(request)
    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
def test_invalid_password_reset_link_offers_another_request(client):
    reset_url = reverse(
        "password_reset_confirm",
        kwargs={"uidb64": "MQ", "token": "invalid-token"},
    )

    response = client.get(reset_url, follow=True)

    assert response.status_code == 200
    assert b"Request another password reset link" in response.content
