"""Wall-clock teacher availability.

Availability is stored as local wall-clock values: a ``TimeField`` for the
start and end of each window plus the IANA zone the teacher chose. Nothing is
converted to ``settings.TIME_ZONE`` or to a UTC offset on save. Task #21 reads
:func:`effective_windows` and resolves the local window against the zone for
the selected date, which is what makes daylight-saving transitions correct.
"""

from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


def validate_iana_timezone(value):
    """Reject anything ``zoneinfo`` cannot load as an IANA timezone name."""
    if not value:
        raise ValidationError("Enter an IANA timezone name.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid IANA timezone name.") from exc


def windows_overlap(first_start, first_end, second_start, second_end):
    """Half-open ``[start, end)`` overlap test.

    Windows that merely touch (``first_end == second_start``) do not overlap.
    """
    return first_start < second_end and second_start < first_end


def teacher_timezone(owner):
    """Return the one configured IANA zone for ``owner``, or ``None``.

    ``None`` means the teacher has no availability yet. Once any rule or
    exception exists all later records must reuse the same zone.
    """
    rule_zone = (
        AvailabilityRule.objects.filter(owner=owner)
        .values_list("timezone", flat=True)
        .first()
    )
    if rule_zone:
        return rule_zone
    return (
        AvailabilityException.objects.filter(owner=owner)
        .values_list("timezone", flat=True)
        .first()
    )


@dataclass(frozen=True)
class LocalWindow:
    """A local wall-clock window together with the IANA zone in force."""

    start_time: time
    end_time: time
    timezone: str


class AvailabilityRule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_rules",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    timezone = models.CharField(max_length=64)

    class Meta:
        ordering = ("weekday", "start_time", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="availability_rule_end_after_start",
            )
        ]

    def clean(self):
        super().clean()
        try:
            validate_iana_timezone(self.timezone)
        except ValidationError as exc:
            raise ValidationError({"timezone": exc.messages}) from exc

    def __str__(self):
        return (
            f"{self.get_weekday_display()} "
            f"{self.start_time:%H:%M}–{self.end_time:%H:%M} ({self.timezone})"
        )


class AvailabilityException(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="availability_exceptions",
    )
    date = models.DateField()
    timezone = models.CharField(max_length=64)

    class Meta:
        ordering = ("date", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "date"),
                name="unique_availability_exception_owner_date",
            )
        ]

    def clean(self):
        super().clean()
        try:
            validate_iana_timezone(self.timezone)
        except ValidationError as exc:
            raise ValidationError({"timezone": exc.messages}) from exc

    def __str__(self):
        return f"Exception {self.date} ({self.timezone})"


class AvailabilityWindow(models.Model):
    """One local window of an exception; zero windows means unavailable."""

    exception = models.ForeignKey(
        AvailabilityException,
        on_delete=models.CASCADE,
        related_name="windows",
    )
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ("start_time", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="availability_window_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.start_time:%H:%M}–{self.end_time:%H:%M}"


def effective_windows(owner, day: date):
    """Return the local windows in force for ``owner`` on local ``day``.

    If an exception exists for that date it replaces every weekly rule for the
    date's weekday, including an exception with no windows (unavailable all
    day). Otherwise the weekly rules for that weekday are returned. The result
    is an empty list when nothing matches. Every returned :class:`LocalWindow`
    carries the IANA zone in force.
    """
    exception = (
        AvailabilityException.objects.filter(owner=owner, date=day)
        .prefetch_related("windows")
        .first()
    )
    if exception is not None:
        return [
            LocalWindow(window.start_time, window.end_time, exception.timezone)
            for window in exception.windows.all()
        ]
    rules = AvailabilityRule.objects.filter(owner=owner, weekday=day.weekday())
    return [
        LocalWindow(rule.start_time, rule.end_time, rule.timezone) for rule in rules
    ]
