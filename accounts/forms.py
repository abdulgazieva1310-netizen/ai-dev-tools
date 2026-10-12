from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm
from django.contrib.auth.password_validation import validate_password

from accounts.models import User


class AccountAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Email or password is incorrect.",
        "inactive": "Email or password is incorrect.",
    }


class AccountPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        users = User.objects.filter(
            email__iexact=email,
            state=User.State.ACTIVE,
        )
        return (user for user in users if user.has_usable_password())


class RegistrationForm(forms.Form):
    email = forms.EmailField()
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        email = cleaned_data.get("email")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")
        if password1 and email:
            validate_password(password1, user=User(email=email))
        return cleaned_data

    def save(self):
        return User.objects.create_user(
            self.cleaned_data["email"], self.cleaned_data["password1"]
        )


class VerificationResendForm(forms.Form):
    email = forms.EmailField()
