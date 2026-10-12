import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from accounts.models import User
from profiles.forms import ProfileSkillForm
from profiles.models import Certificate, Profile, ProfileSkill, Project, Skill


def make_user(email, *, state=User.State.ACTIVE, is_staff=False):
    return User.objects.create_user(
        email,
        password="profile-test-password",
        state=state,
        is_staff=is_staff,
    )


def make_profile(user, *, visibility=Profile.Visibility.MEMBERS_ONLY):
    return Profile.objects.create(
        user=user,
        display_name="Profile owner",
        bio="A short biography",
        languages=["English"],
        visibility=visibility,
    )


@pytest.mark.django_db
def test_owner_creates_one_profile_with_trimmed_deduplicated_languages(client):
    user = make_user("owner@example.com")
    client.force_login(user)

    response = client.post(
        reverse("profile_create"),
        {
            "display_name": "  Casey Learner  ",
            "bio": "  I like learning.  ",
            "languages_text": " English \nenglish\n French ",
            "visibility": Profile.Visibility.MEMBERS_ONLY,
        },
    )

    profile = Profile.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("profile_edit", args=[profile.pk])
    assert profile.display_name == "Casey Learner"
    assert profile.bio == "I like learning."
    assert profile.languages == ["English", "French"]
    assert profile.visibility == Profile.Visibility.MEMBERS_ONLY
    assert client.get(reverse("profile_create")).url == reverse(
        "profile_edit", args=[profile.pk]
    )
    assert Profile.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_owner_can_edit_and_delete_their_profile(client):
    user = make_user("owner@example.com")
    profile = make_profile(user)
    client.force_login(user)

    edit_response = client.post(
        reverse("profile_edit", args=[profile.pk]),
        {
            "display_name": "  New name ",
            "bio": "New bio",
            "languages_text": "Spanish\nspanish\nJapanese",
            "visibility": Profile.Visibility.PRIVATE,
        },
    )
    profile.refresh_from_db()
    assert edit_response.status_code == 302
    assert edit_response.url == reverse("profile_detail", args=[profile.pk])
    assert profile.display_name == "New name"
    assert profile.languages == ["Spanish", "Japanese"]
    assert profile.visibility == Profile.Visibility.PRIVATE

    delete_response = client.post(reverse("profile_delete", args=[profile.pk]))
    assert delete_response.status_code == 302
    assert delete_response.url == reverse("profile_create")
    assert not Profile.objects.filter(pk=profile.pk).exists()


@pytest.mark.django_db
def test_profile_one_to_one_is_enforced_by_database():
    user = make_user("owner@example.com")
    make_profile(user)

    with pytest.raises(IntegrityError), transaction.atomic():
        Profile.objects.create(user=user, display_name="Second profile")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"display_name": "   "}, "display_name"),
        ({"display_name": f"  {'x' * 81}  "}, "display_name"),
        ({"bio": "x" * 2001}, "bio"),
        ({"visibility": "friends"}, "visibility"),
    ],
)
def test_profile_form_rejects_invalid_values_without_saving(client, data, field):
    user = make_user("owner@example.com")
    client.force_login(user)
    payload = {
        "display_name": "Valid Name",
        "bio": "",
        "languages_text": "",
        "visibility": Profile.Visibility.PUBLIC,
        **data,
    }

    response = client.post(reverse("profile_create"), payload)

    assert response.status_code == 200
    assert field in response.context["form"].errors
    assert not Profile.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_profile_can_have_empty_optional_sections(client):
    user = make_user("owner@example.com")
    profile = make_profile(user, visibility=Profile.Visibility.PUBLIC)

    response = client.get(reverse("profile_detail", args=[profile.pk]))

    assert response.status_code == 200
    assert b"No projects listed." in response.content
    assert b"No certificates listed." in response.content
    assert b"No skills listed." in response.content
    assert not Project.objects.exists()
    assert not Certificate.objects.exists()
    assert not ProfileSkill.objects.exists()


@pytest.mark.django_db
def test_owner_can_create_edit_and_delete_project_and_certificate(client):
    user = make_user("owner@example.com")
    profile = make_profile(user)
    client.force_login(user)

    project_response = client.post(
        reverse("project_create", args=[profile.pk]),
        {
            "title": "  Project One ",
            "description": "  Description ",
            "url": "https://example.com/project",
        },
    )
    project = Project.objects.get(profile=profile)
    assert project_response.status_code == 302
    assert project.title == "Project One"
    assert project.description == "Description"
    assert project.url == "https://example.com/project"

    edit_response = client.post(
        reverse("project_edit", args=[profile.pk, project.pk]),
        {"title": "Updated project", "description": "", "url": ""},
    )
    project.refresh_from_db()
    assert edit_response.status_code == 302
    assert project.title == "Updated project"

    certificate_response = client.post(
        reverse("certificate_create", args=[profile.pk]),
        {"title": "Certificate", "description": "", "url": ""},
    )
    certificate = Certificate.objects.get(profile=profile)
    assert certificate_response.status_code == 302

    certificate_edit = client.post(
        reverse("certificate_edit", args=[profile.pk, certificate.pk]),
        {"title": "Updated certificate", "description": "", "url": ""},
    )
    certificate.refresh_from_db()
    assert certificate_edit.status_code == 302
    assert certificate.title == "Updated certificate"

    assert (
        client.post(
            reverse("project_delete", args=[profile.pk, project.pk])
        ).status_code
        == 302
    )
    assert (
        client.post(
            reverse("certificate_delete", args=[profile.pk, certificate.pk])
        ).status_code
        == 302
    )
    assert not Project.objects.exists()
    assert not Certificate.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["http://example.com", "/relative"])
def test_project_and_certificate_forms_reject_non_https_urls(client, url):
    user = make_user("owner@example.com")
    profile = make_profile(user)
    client.force_login(user)

    for route_name in ("project_create", "certificate_create"):
        response = client.post(
            reverse(route_name, args=[profile.pk]),
            {"title": "Entry", "description": "", "url": url},
        )
        assert response.status_code == 200
        assert "url" in response.context["form"].errors

    assert not Project.objects.exists()
    assert not Certificate.objects.exists()


@pytest.mark.django_db
def test_skill_is_normalized_and_reused_across_profiles(client):
    first_user = make_user("first@example.com")
    second_user = make_user("second@example.com")
    first_profile = make_profile(first_user)
    second_profile = make_profile(second_user)
    client.force_login(first_user)

    response = client.post(
        reverse("skill_create", args=[first_profile.pk]),
        {
            "skill_name": "  Python ",
            "intent": ProfileSkill.Intent.TEACHES,
            "level": ProfileSkill.Level.ADVANCED,
        },
    )
    first_interest = ProfileSkill.objects.get(profile=first_profile)
    assert response.status_code == 302
    assert first_interest.skill.name == "Python"
    assert first_interest.skill.normalized_name == "python"

    client.force_login(second_user)
    response = client.post(
        reverse("skill_create", args=[second_profile.pk]),
        {
            "skill_name": "PYTHON",
            "intent": ProfileSkill.Intent.WANTS_TO_LEARN,
            "level": ProfileSkill.Level.BEGINNER,
        },
    )
    second_interest = ProfileSkill.objects.get(profile=second_profile)
    assert response.status_code == 302
    assert second_interest.skill_id == first_interest.skill_id
    assert Skill.objects.filter(normalized_name="python").count() == 1


@pytest.mark.django_db
def test_same_skill_can_have_both_intents_but_not_duplicate_intent(client):
    user = make_user("owner@example.com")
    profile = make_profile(user)
    skill = Skill.objects.create(name="  Django ")
    ProfileSkill.objects.create(
        profile=profile,
        skill=skill,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.ADVANCED,
    )
    client.force_login(user)

    other_intent = client.post(
        reverse("skill_create", args=[profile.pk]),
        {
            "skill_name": "DJANGO",
            "intent": ProfileSkill.Intent.WANTS_TO_LEARN,
            "level": ProfileSkill.Level.BEGINNER,
        },
    )
    duplicate = client.post(
        reverse("skill_create", args=[profile.pk]),
        {
            "skill_name": " django ",
            "intent": ProfileSkill.Intent.TEACHES,
            "level": ProfileSkill.Level.INTERMEDIATE,
        },
    )

    assert other_intent.status_code == 302
    assert duplicate.status_code == 200
    assert "skill_name" in duplicate.context["form"].errors
    assert ProfileSkill.objects.filter(profile=profile).count() == 2
    assert (
        ProfileSkill.objects.filter(
            profile=profile, intent=ProfileSkill.Intent.TEACHES
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_invalid_skill_submission_shows_errors_without_creating_skill(client):
    user = make_user("owner@example.com")
    profile = make_profile(user)
    client.force_login(user)

    response = client.post(
        reverse("skill_create", args=[profile.pk]),
        {
            "skill_name": "   ",
            "intent": "learns",
            "level": "expert",
        },
    )

    assert response.status_code == 200
    assert {"skill_name", "intent", "level"} <= response.context["form"].errors.keys()
    assert Skill.objects.count() == 0
    assert ProfileSkill.objects.count() == 0


@pytest.mark.django_db
def test_profile_skill_duplicate_constraint_and_allowed_choices():
    user = make_user("owner@example.com")
    profile = make_profile(user)
    skill = Skill.objects.create(name="Python")
    ProfileSkill.objects.create(
        profile=profile,
        skill=skill,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.BEGINNER,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ProfileSkill.objects.create(
            profile=profile,
            skill=skill,
            intent=ProfileSkill.Intent.TEACHES,
            level=ProfileSkill.Level.ADVANCED,
        )

    invalid = ProfileSkillForm(
        {"skill_name": "Go", "intent": "watches", "level": "expert"},
        profile=profile,
    )
    assert not invalid.is_valid()
    assert {"intent", "level"} <= invalid.errors.keys()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("visibility", "viewer_kind", "expected"),
    [
        (Profile.Visibility.PUBLIC, "anonymous", 200),
        (Profile.Visibility.PUBLIC, "member", 200),
        (Profile.Visibility.PUBLIC, "owner", 200),
        (Profile.Visibility.PUBLIC, "staff", 200),
        (Profile.Visibility.MEMBERS_ONLY, "anonymous", 404),
        (Profile.Visibility.MEMBERS_ONLY, "member", 200),
        (Profile.Visibility.MEMBERS_ONLY, "owner", 200),
        (Profile.Visibility.MEMBERS_ONLY, "staff", 200),
        (Profile.Visibility.PRIVATE, "anonymous", 404),
        (Profile.Visibility.PRIVATE, "member", 404),
        (Profile.Visibility.PRIVATE, "owner", 200),
        (Profile.Visibility.PRIVATE, "staff", 200),
    ],
)
def test_profile_visibility_matrix(client, visibility, viewer_kind, expected):
    owner = make_user("owner@example.com")
    profile = make_profile(owner, visibility=visibility)
    if viewer_kind == "member":
        viewer = make_user("member@example.com")
    elif viewer_kind == "staff":
        viewer = make_user("staff@example.com", is_staff=True)
    elif viewer_kind == "owner":
        viewer = owner
    else:
        viewer = None
    if viewer:
        client.force_login(viewer)

    response = client.get(reverse("profile_detail", args=[profile.pk]))

    assert response.status_code == expected


@pytest.mark.django_db
def test_inactive_members_and_staff_cannot_read_restricted_profiles(client):
    owner = make_user("owner@example.com")
    profile = make_profile(owner, visibility=Profile.Visibility.PRIVATE)
    for number, is_staff in enumerate((False, True)):
        inactive = make_user(
            f"inactive-{number}@example.com",
            state=User.State.SUSPENDED,
            is_staff=is_staff,
        )
        client.force_login(inactive)
        assert (
            client.get(reverse("profile_detail", args=[profile.pk])).status_code == 404
        )


@pytest.mark.django_db
def test_profile_response_does_not_expose_account_fields(client):
    user = make_user("private-email@example.com")
    profile = make_profile(user)
    client.force_login(user)

    response = client.get(reverse("profile_detail", args=[profile.pk]))

    assert b"private-email@example.com" not in response.content
    assert b"profile-test-password" not in response.content
    assert user.password.encode() not in response.content
    assert b"active" not in response.content
    assert not hasattr(profile, "email")
    assert not hasattr(profile, "password")
    assert not hasattr(profile, "state")


@pytest.mark.django_db
def test_other_accounts_cannot_edit_or_delete_profile_or_entries(client):
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    profile = make_profile(owner)
    other_profile = make_profile(other)
    project = Project.objects.create(profile=profile, title="Project")
    other_project = Project.objects.create(profile=other_profile, title="Other")
    certificate = Certificate.objects.create(profile=profile, title="Certificate")
    other_certificate = Certificate.objects.create(
        profile=other_profile, title="Other certificate"
    )
    skill = Skill.objects.create(name="Django")
    interest = ProfileSkill.objects.create(
        profile=profile,
        skill=skill,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.ADVANCED,
    )
    other_interest = ProfileSkill.objects.create(
        profile=other_profile,
        skill=skill,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.BEGINNER,
    )
    client.force_login(owner)

    assert (
        client.get(reverse("profile_edit", args=[other_profile.pk])).status_code == 404
    )
    assert (
        client.post(reverse("profile_delete", args=[other_profile.pk])).status_code
        == 404
    )
    assert (
        client.post(
            reverse("project_edit", args=[other_profile.pk, project.pk]),
            {"title": "Changed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("project_delete", args=[other_profile.pk, other_project.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("project_edit", args=[profile.pk, other_project.pk]),
            {"title": "Changed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("project_delete", args=[profile.pk, other_project.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("certificate_edit", args=[other_profile.pk, certificate.pk]),
            {"title": "Changed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("certificate_delete", args=[other_profile.pk, other_certificate.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("certificate_edit", args=[profile.pk, other_certificate.pk]),
            {"title": "Changed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("certificate_delete", args=[profile.pk, other_certificate.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("skill_edit", args=[other_profile.pk, interest.pk]),
            {"skill_name": "Python", "intent": "teaches", "level": "beginner"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("skill_delete", args=[other_profile.pk, other_interest.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("skill_edit", args=[profile.pk, other_interest.pk]),
            {"skill_name": "Python", "intent": "teaches", "level": "beginner"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("skill_delete", args=[profile.pk, other_interest.pk])
        ).status_code
        == 404
    )

    profile.refresh_from_db()
    project.refresh_from_db()
    certificate.refresh_from_db()
    interest.refresh_from_db()
    assert profile.display_name == "Profile owner"
    assert project.title == "Project"
    assert certificate.title == "Certificate"
    assert interest.skill.name == "Django"


@pytest.mark.django_db
def test_all_profile_mutations_require_csrf():
    owner = make_user("owner@example.com")
    profile = make_profile(owner)
    project = Project.objects.create(profile=profile, title="Project")
    certificate = Certificate.objects.create(profile=profile, title="Certificate")
    skill = Skill.objects.create(name="Django")
    interest = ProfileSkill.objects.create(
        profile=profile,
        skill=skill,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.ADVANCED,
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    posts = [
        (reverse("profile_create"), {}),
        (reverse("profile_edit", args=[profile.pk]), {}),
        (reverse("profile_delete", args=[profile.pk]), {}),
        (reverse("project_create", args=[profile.pk]), {}),
        (reverse("project_edit", args=[profile.pk, project.pk]), {}),
        (reverse("project_delete", args=[profile.pk, project.pk]), {}),
        (reverse("certificate_create", args=[profile.pk]), {}),
        (reverse("certificate_edit", args=[profile.pk, certificate.pk]), {}),
        (reverse("certificate_delete", args=[profile.pk, certificate.pk]), {}),
        (reverse("skill_create", args=[profile.pk]), {}),
        (reverse("skill_edit", args=[profile.pk, interest.pk]), {}),
        (reverse("skill_delete", args=[profile.pk, interest.pk]), {}),
    ]

    for url, data in posts:
        assert client.post(url, data).status_code == 403
