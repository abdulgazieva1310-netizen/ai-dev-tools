from django import forms
from django.db import IntegrityError, transaction

from profiles.models import Certificate, Profile, ProfileSkill, Project, Skill


class ProfileForm(forms.ModelForm):
    languages_text = forms.CharField(
        label="Languages",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Enter one language per line.",
    )

    class Meta:
        model = Profile
        fields = ("display_name", "bio", "visibility")
        widgets = {"bio": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["languages_text"] = "\n".join(self.instance.languages or [])

    def clean_display_name(self):
        display_name = self.cleaned_data["display_name"].strip()
        if not display_name:
            raise forms.ValidationError("Enter a display name.")
        return display_name

    def clean_languages_text(self):
        languages = []
        seen = set()
        for line in self.cleaned_data["languages_text"].splitlines():
            language = line.strip()
            key = language.casefold()
            if language and key not in seen:
                languages.append(language)
                seen.add(key)
        return languages

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.languages = self.cleaned_data["languages_text"]
        if commit:
            profile.save()
            self.save_m2m()
        return profile


class ProfileTextEntryForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("title", "description", "url")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean_title(self):
        title = self.cleaned_data["title"].strip()
        if not title:
            raise forms.ValidationError("Enter a title.")
        return title

    def clean_url(self):
        url = self.cleaned_data.get("url", "").strip()
        if url and not url.lower().startswith("https://"):
            raise forms.ValidationError("Enter an absolute HTTPS URL.")
        return url


class ProjectForm(ProfileTextEntryForm):
    class Meta(ProfileTextEntryForm.Meta):
        model = Project


class CertificateForm(ProfileTextEntryForm):
    class Meta(ProfileTextEntryForm.Meta):
        model = Certificate


class ProfileSkillForm(forms.Form):
    skill_name = forms.CharField(max_length=100)
    intent = forms.ChoiceField(choices=ProfileSkill.Intent.choices)
    level = forms.ChoiceField(choices=ProfileSkill.Level.choices)

    def __init__(self, *args, profile, instance=None, **kwargs):
        self.profile = profile
        self.instance = instance
        super().__init__(*args, **kwargs)
        if instance and not self.is_bound:
            self.initial.update(
                {
                    "skill_name": instance.skill.name,
                    "intent": instance.intent,
                    "level": instance.level,
                }
            )

    def clean_skill_name(self):
        name = self.cleaned_data["skill_name"].strip()
        if not name:
            raise forms.ValidationError("Enter a skill name.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        skill_name = cleaned_data.get("skill_name")
        intent = cleaned_data.get("intent")
        if skill_name and intent:
            normalized_name = skill_name.casefold()
            duplicate = ProfileSkill.objects.filter(
                profile=self.profile,
                skill__normalized_name=normalized_name,
                intent=intent,
            )
            if self.instance:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    "skill_name",
                    "This skill and intent already appear on your profile.",
                )
        return cleaned_data

    def save(self):
        try:
            with transaction.atomic():
                name = self.cleaned_data["skill_name"]
                skill, _ = Skill.objects.get_or_create(
                    normalized_name=name.casefold(), defaults={"name": name}
                )
                entry = self.instance or ProfileSkill(profile=self.profile)
                entry.skill = skill
                entry.intent = self.cleaned_data["intent"]
                entry.level = self.cleaned_data["level"]
                entry.save()
                return entry
        except IntegrityError as exc:
            raise forms.ValidationError(
                "This skill and intent already appear on your profile."
            ) from exc
