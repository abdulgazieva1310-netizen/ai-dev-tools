from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.models import User

TOKEN_SALT = "accounts.email-verification.v1"
TOKEN_PURPOSE = "verify-email"


def send_verification_email(user, request):
    token = signing.dumps(
        {"purpose": TOKEN_PURPOSE, "user_id": user.pk, "email": user.email},
        salt=TOKEN_SALT,
    )
    verification_url = request.build_absolute_uri(
        reverse("verify_email", kwargs={"token": token})
    )
    message = render_to_string(
        "accounts/email_verification_email.txt",
        {"verification_url": verification_url},
    )
    send_mail(
        "Verify your SkillSwap email",
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def verify_email_token(token):
    try:
        payload = signing.loads(
            token,
            salt=TOKEN_SALT,
            max_age=settings.EMAIL_VERIFICATION_TIMEOUT,
        )
        if payload.get("purpose") != TOKEN_PURPOSE:
            return None
        user = User.objects.get(pk=payload.get("user_id"))
        if user.email != payload.get("email") or user.email_verified_at is not None:
            return None
        return user
    except (
        signing.BadSignature,
        signing.SignatureExpired,
        User.DoesNotExist,
        AttributeError,
    ):
        return None
