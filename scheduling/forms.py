import uuid
from datetime import date, time

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    AvailabilityWindow,
    teacher_timezone,
    validate_iana_timezone,
    windows_overlap,
)
from scheduling.services import available_start_times, parse_utc_offset


def parse_windows(raw):
    """Parse ``09:00-12:00`` lines into ``(start, end)`` time pairs.

    An empty value yields no windows, meaning the teacher is unavailable for
    the whole local date.
    """
    windows = []
    for line_number, line in enumerate((raw or "").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        start_text, separator, end_text = line.partition("-")
        if not separator:
            raise ValidationError(
                f"Line {line_number}: enter a window as start-end, "
                "for example 09:00-12:00."
            )
        try:
            start = time.fromisoformat(start_text.strip())
            end = time.fromisoformat(end_text.strip())
        except ValueError as exc:
            raise ValidationError(
                f"Line {line_number}: use 24-hour times such as 09:00-12:00."
            ) from exc
        if start >= end:
            raise ValidationError(
                f"Line {line_number}: the end time must be after the start time."
            )
        windows.append((start, end))
    ordered = sorted(windows)
    for (start, end), (next_start, next_end) in zip(ordered, ordered[1:]):
        if windows_overlap(start, end, next_start, next_end):
            raise ValidationError("Availability windows for this date overlap.")
    return ordered


class AvailabilityRuleForm(forms.ModelForm):
    class Meta:
        model = AvailabilityRule
        fields = ("weekday", "start_time", "end_time", "timezone")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, owner, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)
        if not self.is_bound and not self.instance.pk:
            existing = teacher_timezone(owner)
            if existing:
                self.initial["timezone"] = existing

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_time")
        end = cleaned_data.get("end_time")
        if start and end and start >= end:
            self.add_error("end_time", "The end time must be after the start time.")

        timezone = cleaned_data.get("timezone")
        if timezone:
            try:
                validate_iana_timezone(timezone)
            except ValidationError:
                timezone = None  # reported by the model's clean()
        if timezone:
            existing = teacher_timezone(self.owner)
            if existing and existing != timezone:
                self.add_error(
                    "timezone",
                    f"Your availability already uses {existing}. "
                    "Every window must use the same timezone.",
                )

        weekday = cleaned_data.get("weekday")
        if timezone and start and end and start < end and weekday is not None:
            others = AvailabilityRule.objects.filter(owner=self.owner, weekday=weekday)
            if self.instance.pk:
                others = others.exclude(pk=self.instance.pk)
            for other in others:
                if windows_overlap(start, end, other.start_time, other.end_time):
                    self.add_error(
                        "start_time",
                        "This window overlaps another window on the same weekday.",
                    )
                    break
        return cleaned_data


class AvailabilityExceptionForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    timezone = forms.CharField(max_length=64)
    windows = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=(
            "One window per line, for example 09:00-12:00. "
            "Leave empty to be unavailable all day."
        ),
    )

    def __init__(self, *args, owner, instance=None, **kwargs):
        self.owner = owner
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance is not None and not self.is_bound:
            self.initial.update(
                {
                    "date": instance.date,
                    "timezone": instance.timezone,
                    "windows": "\n".join(
                        f"{window.start_time:%H:%M}-{window.end_time:%H:%M}"
                        for window in instance.windows.all()
                    ),
                }
            )
        elif not self.is_bound:
            existing = teacher_timezone(owner)
            if existing:
                self.initial["timezone"] = existing

    def clean_timezone(self):
        timezone = self.cleaned_data["timezone"].strip()
        validate_iana_timezone(timezone)
        return timezone

    def clean(self):
        cleaned_data = super().clean()
        timezone = cleaned_data.get("timezone")
        if timezone:
            existing = teacher_timezone(self.owner)
            if existing and existing != timezone:
                self.add_error(
                    "timezone",
                    f"Your availability already uses {existing}. "
                    "Every window must use the same timezone.",
                )

        date = cleaned_data.get("date")
        if date is not None:
            duplicates = AvailabilityException.objects.filter(
                owner=self.owner, date=date
            )
            if self.instance is not None and self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error(
                    "date",
                    "An availability exception already exists for this date.",
                )

        try:
            self.window_pairs = parse_windows(cleaned_data.get("windows"))
        except ValidationError as error:
            self.add_error("windows", error)
            self.window_pairs = []
        return cleaned_data

    def save(self):
        with transaction.atomic():
            exception = self.instance or AvailabilityException(owner=self.owner)
            exception.date = self.cleaned_data["date"]
            exception.timezone = self.cleaned_data["timezone"]
            exception.save()
            exception.windows.all().delete()
            AvailabilityWindow.objects.bulk_create(
                [
                    AvailabilityWindow(
                        exception=exception, start_time=start, end_time=end
                    )
                    for start, end in self.window_pairs
                ]
            )
        return exception


class BookingForm(forms.Form):
    """Server-rendered confirmation form for one live lesson slot.

    The hidden ``idempotency_key`` is generated server-side when the page is
    rendered and stored on the booking, so a repeat submission cannot write a
    second booking.
    """

    idempotency_key = forms.CharField(max_length=255, widget=forms.HiddenInput)
    local_date = forms.DateField(widget=forms.HiddenInput)
    start_time = forms.ChoiceField(widget=forms.RadioSelect)
    duration_minutes = forms.IntegerField(widget=forms.HiddenInput)
    utc_offset = forms.CharField(
        required=False,
        max_length=6,
        help_text="Only needed to disambiguate a repeated fall-back time.",
        widget=forms.TextInput(attrs={"placeholder": "-05:00"}),
    )

    def __init__(self, *args, listing, learner, **kwargs):
        self.listing = listing
        self.learner = learner
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", uuid.uuid4().hex)
            self.initial.setdefault("duration_minutes", listing.duration_minutes)
        self.fields["start_time"].choices = self._offered_choices()

    def _selected_date(self):
        raw = (
            self.data.get("local_date")
            if self.is_bound
            else self.initial.get("local_date")
        )
        if isinstance(raw, date):
            return raw
        if raw in (None, ""):
            return None
        try:
            return date.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return None

    def _offered_choices(self):
        day = self._selected_date()
        if day is None or self.listing.listing_type != self.listing.Type.LIVE:
            return []
        starts = available_start_times(
            self.listing.owner, day, self.listing.duration_minutes
        )
        return [(start.strftime("%H:%M"), start.strftime("%H:%M")) for start in starts]

    def clean_start_time(self):
        value = self.cleaned_data["start_time"]
        try:
            return time.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError("Choose a start time.") from exc

    def clean_duration_minutes(self):
        duration = self.cleaned_data["duration_minutes"]
        if self.listing.duration_minutes != duration:
            raise forms.ValidationError("Use the lesson's configured duration.")
        if duration not in range(15, 181, 15):
            raise forms.ValidationError(
                "Use a 15-minute increment between 15 and 180 minutes."
            )
        return duration

    def clean_utc_offset(self):
        raw = self.cleaned_data.get("utc_offset")
        try:
            return parse_utc_offset(raw)
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class MeetingLinkForm(forms.Form):
    meeting_url = forms.URLField(max_length=500)
