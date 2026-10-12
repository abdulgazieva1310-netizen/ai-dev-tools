from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from accounts.forms import AccountAuthenticationForm, AccountPasswordResetForm
from accounts.views import (
    RegistrationView,
    email_verification_required,
    resend_verification,
    verification_resend_done,
    verify_email,
)

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path(
        "verify-email/required/",
        email_verification_required,
        name="email_verification_required",
    ),
    path("verify-email/resend/", resend_verification, name="resend_verification"),
    path(
        "verify-email/resend/done/",
        verification_resend_done,
        name="verification_resend_done",
    ),
    path("verify-email/<str:token>/", verify_email, name="verify_email"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            authentication_form=AccountAuthenticationForm,
            template_name="accounts/login.html",
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            form_class=AccountPasswordResetForm,
            template_name="accounts/password_reset_form.html",
            email_template_name="accounts/password_reset_email.txt",
            subject_template_name="accounts/password_reset_subject.txt",
            success_url=reverse_lazy("password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
