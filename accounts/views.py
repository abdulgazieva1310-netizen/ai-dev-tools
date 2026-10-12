from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.generic import FormView

from accounts.email_verification import send_verification_email, verify_email_token
from accounts.forms import RegistrationForm, VerificationResendForm


class RegistrationView(FormView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("login")

    def form_valid(self, form):
        user = form.save()
        try:
            send_verification_email(user, self.request)
        except Exception:
            return render(
                self.request,
                "accounts/verification_delivery_error.html",
                {"user": user},
                status=503,
            )
        return super().form_valid(form)


@require_GET
def verify_email(request, token):
    user = verify_email_token(token)
    if user is None or not user.__class__.objects.filter(
        pk=user.pk, email_verified_at__isnull=True
    ).update(email_verified_at=timezone.now()):
        return render(request, "accounts/verification_invalid.html", status=400)
    return render(request, "accounts/verification_complete.html")


@login_required
def resend_verification(request):
    if request.method == "POST":
        form = VerificationResendForm(request.POST)
        if form.is_valid():
            requested_email = form.cleaned_data["email"]
            user = request.user
            if (
                user.email == user.__class__.objects.normalize_email(requested_email)
                and user.email_verified_at is None
            ):
                try:
                    send_verification_email(user, request)
                except Exception:
                    pass
            return redirect("verification_resend_done")
    else:
        form = VerificationResendForm(initial={"email": request.user.email})
    return render(request, "accounts/verification_resend.html", {"form": form})


@login_required
@require_GET
def verification_resend_done(request):
    return render(request, "accounts/verification_resend_done.html")


def email_verified_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.email_verified_at is None:
            return redirect("email_verification_required")
        return view_func(request, *args, **kwargs)

    return wrapped


@login_required
@require_GET
def email_verification_required(request):
    return render(request, "accounts/email_verification_required.html")
