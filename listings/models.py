from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Category(models.Model):
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


class SkillCategory(models.Model):
    skill = models.OneToOneField(
        "profiles.Skill", on_delete=models.CASCADE, related_name="category_assignment"
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="skill_assignments"
    )

    def __str__(self):
        return f"{self.skill} — {self.category}"


class Listing(models.Model):
    class Type(models.TextChoices):
        LIVE = "live", "Live lesson"
        TRANSCRIPT = "transcript", "Transcript"

    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_REVIEW = "pending_review", "Pending review"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"
        REMOVED = "removed", "Removed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings"
    )
    skill = models.ForeignKey(
        "profiles.Skill",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="listings",
    )
    listing_type = models.CharField(
        max_length=20, choices=Type.choices, default=Type.LIVE
    )
    title = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    learning_outcomes = models.TextField(blank=True)
    level = models.CharField(max_length=20, choices=Level.choices, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.DRAFT)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(listing_type__in=("live", "transcript")),
                name="listing_type_allowed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    state__in=(
                        "draft",
                        "pending_review",
                        "published",
                        "rejected",
                        "removed",
                    )
                ),
                name="listing_state_allowed",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    level__in=("", "beginner", "intermediate", "advanced")
                ),
                name="listing_level_allowed",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__isnull=True)
                | models.Q(duration_minutes__in=tuple(range(15, 181, 15))),
                name="listing_duration_allowed",
            ),
        ]

    @property
    def category(self):
        if not self.skill_id:
            return None
        assignment = getattr(self.skill, "category_assignment", None)
        return assignment.category if assignment else None

    def clean(self):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.learning_outcomes = "\n".join(
            line.strip()
            for line in (self.learning_outcomes or "").splitlines()
            if line.strip()
        )
        self.rejection_reason = (self.rejection_reason or "").strip()
        super().clean()

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.learning_outcomes = "\n".join(
            line.strip()
            for line in (self.learning_outcomes or "").splitlines()
            if line.strip()
        )
        self.rejection_reason = (self.rejection_reason or "").strip()
        super().save(*args, **kwargs)

    def validate_complete(self):
        errors = {}
        if not self.title.strip():
            errors["title"] = "Enter a title before submitting."
        if not self.description.strip():
            errors["description"] = "Enter a description before submitting."
        if not self.learning_outcomes.strip():
            errors["learning_outcomes"] = "Enter at least one learning outcome."
        if not self.skill_id:
            errors["skill"] = "Choose a skill before submitting."
        elif not hasattr(self.skill, "category_assignment"):
            errors["skill"] = "Choose a categorized skill before submitting."
        if self.level not in Listing.Level.values:
            errors["level"] = "Choose a learner level before submitting."
        if self.duration_minutes not in range(15, 181, 15):
            errors["duration_minutes"] = "Choose 15 to 180 minutes in 15-minute steps."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title or f"Draft listing {self.pk}"
