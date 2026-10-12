from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        return super().normalize_email(email).strip().casefold()

    def get_by_natural_key(self, email):
        return self.get(email=self.normalize_email(email))

    def create_user(self, email, password=None, **extra_fields):
        email = self.normalize_email(email or "")
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("state", User.State.ACTIVE)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have staff and superuser permissions")
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DELETION_PENDING = "deletion_pending", "Deletion pending"
        DELETED = "deleted", "Deleted"

    email = models.EmailField(unique=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.ACTIVE)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    @property
    def is_active(self):
        return self.state == self.State.ACTIVE

    def save(self, *args, **kwargs):
        if self.email:
            self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class ExternalIdentity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="identities")
    provider = models.CharField(max_length=32)
    subject = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "subject"), name="unique_external_provider_subject"
            ),
            models.UniqueConstraint(
                fields=("provider", "user"), name="unique_external_provider_user"
            ),
        ]
