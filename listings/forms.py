from django import forms

from listings.models import Category, Listing
from profiles.models import Skill


class ListingForm(forms.ModelForm):
    skill = forms.ModelChoiceField(
        queryset=Skill.objects.none(),
        required=False,
        empty_label="Choose a categorized skill",
    )
    title = forms.CharField(max_length=120, required=False)
    description = forms.CharField(
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    learning_outcomes = forms.CharField(
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Enter one learning outcome per line.",
    )
    level = forms.ChoiceField(
        choices=(("", "Choose a level"), *Listing.Level.choices),
        required=False,
    )
    duration_minutes = forms.IntegerField(required=False, min_value=15, max_value=180)

    class Meta:
        model = Listing
        fields = (
            "skill",
            "title",
            "description",
            "learning_outcomes",
            "level",
            "duration_minutes",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["skill"].queryset = (
            Skill.objects.filter(category_assignment__isnull=False)
            .select_related("category_assignment__category")
            .order_by("name")
        )

    def clean_title(self):
        return self.cleaned_data["title"].strip()

    def clean_description(self):
        return self.cleaned_data["description"].strip()

    def clean_learning_outcomes(self):
        lines = [
            line.strip()
            for line in self.cleaned_data["learning_outcomes"].splitlines()
            if line.strip()
        ]
        return "\n".join(lines)

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get("duration_minutes")
        if duration is not None and duration % 15:
            raise forms.ValidationError("Duration must use 15-minute increments.")
        return duration

    def validate_for_submission(self, listing):
        try:
            listing.validate_complete()
        except forms.ValidationError as error:
            if hasattr(error, "error_dict"):
                for field, errors in error.error_dict.items():
                    target = field if field in self.fields else None
                    for item in errors:
                        self.add_error(target, item)
            else:
                self.add_error(None, error)


class CategoryAdminForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name",)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Enter a category name.")
        return name


class ListingModerationForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = ("state", "rejection_reason")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        state = self.instance.state
        transitions = {
            Listing.State.PENDING_REVIEW: (
                Listing.State.PENDING_REVIEW,
                Listing.State.PUBLISHED,
                Listing.State.REJECTED,
            ),
            Listing.State.PUBLISHED: (
                Listing.State.PUBLISHED,
                Listing.State.REMOVED,
            ),
        }
        allowed = transitions.get(state, (state,))
        self.fields["state"].choices = [
            choice for choice in Listing.State.choices if choice[0] in allowed
        ]

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("state") == Listing.State.REJECTED
            and not (cleaned_data.get("rejection_reason") or "").strip()
        ):
            self.add_error(
                "rejection_reason", "Enter a reason when rejecting a listing."
            )
        return cleaned_data
