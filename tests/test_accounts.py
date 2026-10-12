import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction

from accounts.models import User


@pytest.mark.django_db
def test_user_email_is_normalized_and_unique():
    user = User.objects.create_user("  Person@Example.COM ", "password")

    assert user.email == "person@example.com"


@pytest.mark.django_db
def test_user_email_duplicate_is_rejected_when_only_case_differs():
    User.objects.create_user("person@example.com", "password")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("PERSON@EXAMPLE.COM", "another-password")


@pytest.mark.django_db
def test_user_email_duplicate_is_rejected_when_only_whitespace_differs():
    User.objects.create_user("person@example.com", "password")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("  person@example.com  ", "another-password")


def test_create_user_rejects_whitespace_only_email():
    with pytest.raises(ValueError, match="email address is required"):
        User.objects.create_user("   ", "password")


@pytest.mark.django_db
def test_user_password_is_hashed_and_checks_correctly():
    user = User.objects.create_user("person@example.com", "correct-horse")

    assert user.password != "correct-horse"
    assert user.check_password("correct-horse")
    assert not user.check_password("wrong-password")


@pytest.mark.django_db
def test_user_creation_defaults_to_active_and_unverified():
    user = User.objects.create_user("person@example.com", "password")

    assert user.state == User.State.ACTIVE
    assert user.is_active
    assert user.email_verified_at is None


@pytest.mark.django_db
def test_only_active_state_can_authenticate():
    user = User.objects.create_user("person@example.com", "password")

    assert authenticate(username="PERSON@example.com", password="password") == user
    for state in (
        User.State.SUSPENDED,
        User.State.DELETION_PENDING,
        User.State.DELETED,
    ):
        user.state = state
        user.save(update_fields=["state"])
        assert not user.is_active
        assert authenticate(username=user.email, password="password") is None
