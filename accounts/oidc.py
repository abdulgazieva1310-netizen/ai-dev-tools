import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured, SuspiciousOperation
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import (
    OIDCAuthenticationCallbackView,
    OIDCAuthenticationRequestView,
)

from accounts.models import ExternalIdentity


def callback_url(request):
    if not google_oidc_configured():
        raise ImproperlyConfigured("Google OIDC is not configured")
    return settings.GOOGLE_OIDC_CALLBACK_URL


def google_oidc_configured():
    return all(
        (
            settings.GOOGLE_OIDC_CLIENT_ID,
            settings.GOOGLE_OIDC_CLIENT_SECRET,
            settings.GOOGLE_OIDC_CALLBACK_URL,
        )
    )


class GoogleLoginView(OIDCAuthenticationRequestView):
    def get(self, request):
        if not google_oidc_configured():
            return render(request, "accounts/google_login_unavailable.html", status=503)
        return super().get(request)

    def get_extra_params(self, request):
        return {"redirect_uri": callback_url(request)}


class GoogleCallbackView(OIDCAuthenticationCallbackView):
    def login_failure(self):
        return render(self.request, "accounts/google_login_failed.html", status=400)

    def get(self, request):
        if request.GET.get("error"):
            request.session.pop("google_link_user_id", None)
            return self.login_failure()
        state = request.GET.get("state")
        states = request.session.get("oidc_states", {})
        state_data = states.get(state) if isinstance(states, dict) else None
        if request.GET.get("code") and (
            not isinstance(state_data, dict)
            or time.time() - state_data.get("added_on", 0) > settings.OIDC_STATE_TIMEOUT
        ):
            if state:
                if isinstance(states, dict):
                    states.pop(state, None)
                    request.session.modified = True
            request.session.pop("google_link_user_id", None)
            return self.login_failure()
        try:
            return super().get(request)
        except Exception:
            return self.login_failure()
        finally:
            request.session.pop("google_link_user_id", None)


@login_required
def link_google_identity(request):
    if not google_oidc_configured():
        return render(request, "accounts/google_login_unavailable.html", status=503)
    request.session["google_link_user_id"] = request.user.pk
    return redirect("google_login")


class GoogleOIDCBackend(OIDCAuthenticationBackend):
    def authenticate(self, request, **kwargs):
        try:
            return super().authenticate(request, **kwargs)
        except Exception:
            # Provider responses and token errors can contain secrets or claims.
            return None

    def store_tokens(self, access_token, id_token):
        return None

    def get_or_create_user(self, access_token, id_token, claims):
        subject = claims.get("sub")
        email = claims.get("email")
        if (
            not subject
            or not email
            or claims.get("email_verified") is not True
            or claims.get("iss")
            not in {"https://accounts.google.com", "accounts.google.com"}
            or self.OIDC_RP_CLIENT_ID not in claims.get("aud", [])
            and claims.get("aud") != self.OIDC_RP_CLIENT_ID
        ):
            return None

        User = get_user_model()
        link_user_id = self.request.session.get("google_link_user_id")
        with transaction.atomic():
            identity = (
                ExternalIdentity.objects.select_related("user")
                .filter(provider="google", subject=subject)
                .first()
            )
            if identity:
                if link_user_id and identity.user_id != link_user_id:
                    return None
                return identity.user if identity.user.is_active else None

            if link_user_id:
                user = User.objects.filter(
                    pk=link_user_id, state=User.State.ACTIVE
                ).first()
                if user is None:
                    return None
                normalized_email = User.objects.normalize_email(email)
                if (
                    User.objects.filter(email=normalized_email)
                    .exclude(pk=user.pk)
                    .exists()
                ):
                    return None
            else:
                normalized_email = User.objects.normalize_email(email)
                if User.objects.filter(email=normalized_email).exists():
                    return None
                user = User.objects.create_user(
                    normalized_email,
                    password=None,
                    email_verified_at=timezone.now(),
                )

            try:
                ExternalIdentity.objects.create(
                    user=user, provider="google", subject=subject
                )
            except IntegrityError:
                raise SuspiciousOperation("External identity is already linked")
            return user

    def get_token(self, payload):
        payload["redirect_uri"] = callback_url(self.request)
        return super().get_token(payload)
