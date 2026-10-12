from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models


def normalize_languages(languages):
    if not isinstance(languages, list):
        raise ValidationError({"languages": "Enter a list of language labels."})
    normalized = []
    seen = set()
    for language in languages:
        if not isinstance(language, str):
            raise ValidationError({"languages": "Language labels must be text."})
        label = language.strip()
        key = label.casefold()
        if label and key not in seen:
            normalized.append(label)
            seen.add(key)
    return normalized


class Profile(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        MEMBERS_ONLY = "members_only", "Members only"
        PRIVATE = "private", "Private"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField(max_length=80)
    bio = models.CharField(max_length=2000, blank=True)
    languages = models.JSONField(default=list, blank=True)
    visibility = models.CharField(
        max_length=20, choices=Visibility.choices, default=Visibility.MEMBERS_ONLY
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    visibility__in=("public", "members_only", "private")
                ),
                name="profile_visibility_allowed",
            )
        ]

    def clean(self):
        self.display_name = (self.display_name or "").strip()
        self.bio = (self.bio or "").strip()
        self.languages = normalize_languages(self.languages)
        super().clean()

    def save(self, *args, **kwargs):
        self.display_name = (self.display_name or "").strip()
        self.bio = (self.bio or "").strip()
        self.languages = normalize_languages(self.languages)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name


class ProfileTextEntry(models.Model):
    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="%(class)ss"
    )
    title = models.CharField(max_length=120)
    description = models.CharField(max_length=2000, blank=True)
    url = models.URLField(max_length=500, blank=True)

    class Meta:
        abstract = True

    def clean(self):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.url = (self.url or "").strip()
        if self.url:
            URLValidator(schemes=["https"])(self.url)
            parts = urlsplit(self.url)
            if not parts.netloc:
                raise ValidationError({"url": "Enter an absolute HTTPS URL."})
        super().clean()

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.url = (self.url or "").strip()
        super().save(*args, **kwargs)


class Project(ProfileTextEntry):
    pass


class Certificate(ProfileTextEntry):
    pass


class Skill(models.Model):
    name = models.CharField(max_length=100)
    normalized_name = models.CharField(max_length=100, unique=True, editable=False)

    def clean(self):
        self.name = (self.name or "").strip()
        self.normalized_name = self.name.casefold()
        super().clean()

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProfileSkill(models.Model):
    class Intent(models.TextChoices):
        TEACHES = "teaches", "Teaches"
        WANTS_TO_LEARN = "wants_to_learn", "Wants to learn"

    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="skill_interests"
    )
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, related_name="profiles")
    intent = models.CharField(max_length=20, choices=Intent.choices)
    level = models.CharField(max_length=20, choices=Level.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "skill", "intent"),
                name="unique_profile_skill_intent",
            ),
            models.CheckConstraint(
                condition=models.Q(intent__in=("teaches", "wants_to_learn")),
                name="profile_skill_intent_allowed",
            ),
            models.CheckConstraint(
                condition=models.Q(level__in=("beginner", "intermediate", "advanced")),
                name="profile_skill_level_allowed",
            ),
        ]

    def __str__(self):
        return f"{self.skill} ({self.get_intent_display()})"
