from django import forms
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from profiles.forms import (
    CertificateForm,
    ProfileForm,
    ProfileSkillForm,
    ProjectForm,
)
from profiles.models import Certificate, Profile, ProfileSkill, Project


def get_owned_profile(request, profile_id):
    if not request.user.is_active:
        raise Http404
    return get_object_or_404(Profile, pk=profile_id, user=request.user)


def profile_visible_to(profile, viewer):
    if viewer.is_authenticated and viewer.pk == profile.user_id:
        return True
    if profile.visibility == Profile.Visibility.PUBLIC:
        return True
    if not viewer.is_authenticated or not viewer.is_active:
        return False
    if profile.visibility == Profile.Visibility.MEMBERS_ONLY:
        return True
    return profile.visibility == Profile.Visibility.PRIVATE and viewer.is_staff


@require_http_methods(["GET"])
def profile_detail(request, profile_id):
    profile = get_object_or_404(Profile, pk=profile_id)
    if not profile_visible_to(profile, request.user):
        raise Http404
    is_owner = request.user.is_authenticated and request.user.pk == profile.user_id
    return render(
        request,
        "profiles/profile_detail.html",
        {
            "profile": profile,
            "is_owner": is_owner,
            "projects": profile.projects.all(),
            "certificates": profile.certificates.all(),
            "skill_interests": profile.skill_interests.select_related("skill").all(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_create(request):
    if not request.user.is_active:
        raise Http404
    existing = Profile.objects.filter(user=request.user).first()
    if existing:
        return redirect("profile_edit", profile_id=existing.pk)
    form = ProfileForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                profile = form.save(commit=False)
                profile.user = request.user
                profile.save()
        except IntegrityError:
            profile = get_object_or_404(Profile, user=request.user)
        return redirect("profile_edit", profile_id=profile.pk)
    return render(
        request,
        "profiles/profile_form.html",
        {"form": form, "heading": "Create your profile", "profile": None},
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request, profile_id):
    profile = get_owned_profile(request, profile_id)
    form = ProfileForm(
        request.POST if request.method == "POST" else None, instance=profile
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("profile_detail", profile_id=profile.pk)
    return render(
        request,
        "profiles/profile_form.html",
        {"form": form, "heading": "Edit your profile", "profile": profile},
    )


@login_required
@require_POST
def profile_delete(request, profile_id):
    profile = get_owned_profile(request, profile_id)
    profile.delete()
    return redirect("profile_create")


def text_entry_form(request, profile_id, model, form_class, title, entry_id=None):
    profile = get_owned_profile(request, profile_id)
    if entry_id is None:
        entry = None
    else:
        entry = get_object_or_404(model, pk=entry_id, profile=profile)
    form = form_class(
        request.POST if request.method == "POST" else None, instance=entry
    )
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.profile = profile
        entry.save()
        return redirect("profile_detail", profile_id=profile.pk)
    return render(
        request,
        "profiles/entry_form.html",
        {
            "form": form,
            "heading": title,
            "profile": profile,
            "entry": entry,
            "entry_type": title.split()[0].lower(),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def project_create(request, profile_id):
    return text_entry_form(request, profile_id, Project, ProjectForm, "Project entry")


@login_required
@require_http_methods(["GET", "POST"])
def project_edit(request, profile_id, entry_id):
    return text_entry_form(
        request, profile_id, Project, ProjectForm, "Project entry", entry_id
    )


@login_required
@require_POST
def project_delete(request, profile_id, entry_id):
    profile = get_owned_profile(request, profile_id)
    entry = get_object_or_404(Project, pk=entry_id, profile=profile)
    entry.delete()
    return redirect("profile_detail", profile_id=profile.pk)


@login_required
@require_http_methods(["GET", "POST"])
def certificate_create(request, profile_id):
    return text_entry_form(
        request, profile_id, Certificate, CertificateForm, "Certificate entry"
    )


@login_required
@require_http_methods(["GET", "POST"])
def certificate_edit(request, profile_id, entry_id):
    return text_entry_form(
        request, profile_id, Certificate, CertificateForm, "Certificate entry", entry_id
    )


@login_required
@require_POST
def certificate_delete(request, profile_id, entry_id):
    profile = get_owned_profile(request, profile_id)
    entry = get_object_or_404(Certificate, pk=entry_id, profile=profile)
    entry.delete()
    return redirect("profile_detail", profile_id=profile.pk)


@login_required
@require_http_methods(["GET", "POST"])
def skill_create(request, profile_id):
    profile = get_owned_profile(request, profile_id)
    form = ProfileSkillForm(
        request.POST if request.method == "POST" else None, profile=profile
    )
    return skill_form_response(request, profile, form)


@login_required
@require_http_methods(["GET", "POST"])
def skill_edit(request, profile_id, entry_id):
    profile = get_owned_profile(request, profile_id)
    entry = get_object_or_404(ProfileSkill, pk=entry_id, profile=profile)
    form = ProfileSkillForm(
        request.POST if request.method == "POST" else None,
        profile=profile,
        instance=entry,
    )
    return skill_form_response(request, profile, form, entry)


def skill_form_response(request, profile, form, entry=None):
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except forms.ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect("profile_detail", profile_id=profile.pk)
    return render(
        request,
        "profiles/skill_form.html",
        {"form": form, "profile": profile, "entry": entry},
    )


@login_required
@require_POST
def skill_delete(request, profile_id, entry_id):
    profile = get_owned_profile(request, profile_id)
    entry = get_object_or_404(ProfileSkill, pk=entry_id, profile=profile)
    entry.delete()
    return redirect("profile_detail", profile_id=profile.pk)
