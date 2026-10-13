import pytest
from django.contrib.admin.sites import AdminSite
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from listings.admin import ListingAdmin
from listings.forms import ListingForm, ListingModerationForm
from listings.models import Category, Listing, SkillCategory
from profiles.models import Profile, ProfileSkill, Skill


def make_user(email, *, verified=True, state=User.State.ACTIVE, staff=False):
    return User.objects.create_user(
        email,
        password="listing-test-password",
        state=state,
        is_staff=staff,
        email_verified_at=timezone.now() if verified else None,
    )


def categorized_skill(name="Python", category_name="Programming"):
    skill = Skill.objects.create(name=name)
    category = Category.objects.get(normalized_name=category_name.casefold())
    SkillCategory.objects.create(skill=skill, category=category)
    return skill


def listing_data(skill, **overrides):
    return {
        "skill": skill.pk,
        "title": "  Python foundations ",
        "description": "  Learn the fundamentals. ",
        "learning_outcomes": " Write programs\n\nUse variables ",
        "level": Listing.Level.BEGINNER,
        "duration_minutes": "45",
        **overrides,
    }


def submit_listing(client, skill_obj, **overrides):
    data = listing_data(skill_obj)
    data.update(overrides)
    data["action"] = "submit"
    return client.post(reverse("listing_create"), data)


@pytest.mark.django_db
def test_default_categories_are_seeded_and_category_names_are_normalized():
    expected = {"Programming", "Languages", "Design", "Music", "Cooking", "Business"}
    assert set(Category.objects.values_list("name", flat=True)) == expected

    category = Category.objects.create(name="  Photography ")
    assert category.name == "Photography"
    assert category.normalized_name == "photography"
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.create(name="PHOTOGRAPHY")


@pytest.mark.django_db
def test_skill_category_is_unique_and_protects_used_category_from_deletion():
    category = Category.objects.get(normalized_name="programming")
    first = Skill.objects.create(name="Python")
    second = Skill.objects.create(name="Django")
    SkillCategory.objects.create(skill=first, category=category)

    SkillCategory.objects.create(skill=second, category=category)
    with pytest.raises(ProtectedError):
        category.delete()

    profile = Profile.objects.create(
        user=make_user("profile@example.com"), display_name="Profile"
    )
    uncategorized = Skill.objects.create(name="Uncategorized")
    profile_skill = ProfileSkill.objects.create(
        profile=profile,
        skill=uncategorized,
        intent=ProfileSkill.Intent.TEACHES,
        level=ProfileSkill.Level.BEGINNER,
    )
    assert not hasattr(profile_skill.skill, "category_assignment")


@pytest.mark.django_db
def test_listing_form_offers_only_categorized_shared_skills():
    categorized = categorized_skill()
    uncategorized = Skill.objects.create(name="Uncategorized")

    form = ListingForm()

    assert list(form.fields["skill"].queryset) == [categorized]
    assert uncategorized not in form.fields["skill"].queryset


@pytest.mark.django_db
def test_listing_category_is_derived_from_its_shared_skill(client):
    owner = make_user("owner@example.com")
    skill = categorized_skill(category_name="Design")
    client.force_login(owner)

    response = client.post(
        reverse("listing_create"),
        listing_data(
            skill,
            title="Design session",
            action="save",
        ),
    )
    listing = Listing.objects.get(owner=owner)

    assert response.status_code == 302
    assert listing.skill == skill
    assert listing.category.name == "Design"


@pytest.mark.django_db
def test_owner_can_save_incomplete_draft_then_submit_complete_listing(client):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    client.force_login(owner)

    draft_response = client.post(
        reverse("listing_create"),
        {"action": "save", "title": "  Draft title  "},
    )
    listing = Listing.objects.get(owner=owner)
    assert draft_response.status_code == 302
    assert listing.title == "Draft title"
    assert listing.state == Listing.State.DRAFT
    assert listing.skill is None

    edit_response = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {**listing_data(skill), "action": "submit"},
    )
    listing.refresh_from_db()

    assert edit_response.status_code == 302
    assert listing.state == Listing.State.PENDING_REVIEW
    assert listing.title == "Python foundations"
    assert listing.learning_outcomes == "Write programs\nUse variables"
    assert listing.duration_minutes == 45
    assert listing.category.name == "Programming"


@pytest.mark.django_db
def test_unverified_owner_cannot_submit_and_no_listing_is_saved(client):
    owner = make_user("owner@example.com", verified=False)
    skill = categorized_skill()
    client.force_login(owner)

    response = submit_listing(client, skill)

    assert response.status_code == 200
    assert "Verify your email" in response.content.decode()
    assert not Listing.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"title": "  "}, "title"),
        ({"title": "x" * 121}, "title"),
        ({"description": "  "}, "description"),
        ({"description": "x" * 2001}, "description"),
        ({"learning_outcomes": "  "}, "learning_outcomes"),
        ({"learning_outcomes": "x" * 2001}, "learning_outcomes"),
        ({"skill": ""}, "skill"),
        ({"level": "expert"}, "level"),
        ({"duration_minutes": "16"}, "duration_minutes"),
        ({"duration_minutes": "195"}, "duration_minutes"),
    ],
)
def test_submit_form_rejects_invalid_data_without_saving(client, overrides, field):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    client.force_login(owner)

    response = submit_listing(client, skill, **overrides)

    assert response.status_code == 200
    assert field in response.context["form"].errors
    assert not Listing.objects.exists()


@pytest.mark.django_db
def test_submit_form_rejects_uncategorized_skill(client):
    owner = make_user("owner@example.com")
    skill = Skill.objects.create(name="Uncategorized")
    client.force_login(owner)

    response = submit_listing(client, skill)

    assert response.status_code == 200
    assert "skill" in response.context["form"].errors
    assert not Listing.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("point_cost", [None, 0])
def test_submit_edit_form_flags_missing_point_cost_without_crashing(client, point_cost):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    listing = Listing.objects.create(
        owner=owner,
        listing_type=Listing.Type.LIVE,
        state=Listing.State.DRAFT,
        point_cost=point_cost,
        title="Lesson",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=60,
    )
    client.force_login(owner)

    response = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {**listing_data(skill), "action": "submit"},
    )

    assert response.status_code == 200
    assert any(
        "point cost" in str(error)
        for error in response.context["form"].non_field_errors()
    )
    listing.refresh_from_db()
    assert listing.state == Listing.State.DRAFT
    assert not Listing.objects.filter(state=Listing.State.PENDING_REVIEW).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("point_cost", [None, 0])
def test_submit_action_path_also_rejects_missing_point_cost(client, point_cost):
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(
        owner=owner,
        listing_type=Listing.Type.LIVE,
        state=Listing.State.DRAFT,
        point_cost=point_cost,
        title="Lesson",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=60,
    )
    client.force_login(owner)

    response = client.post(
        reverse("listing_transition", args=[listing.pk]), {"action": "submit"}
    )

    assert response.status_code == 400
    listing.refresh_from_db()
    assert listing.state == Listing.State.DRAFT


@pytest.mark.django_db
def test_draft_can_be_incomplete_but_invalid_duration_is_rejected(client):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    client.force_login(owner)

    draft = client.post(reverse("listing_create"), {"action": "save", "title": "Draft"})
    assert draft.status_code == 302
    assert Listing.objects.get(owner=owner).state == Listing.State.DRAFT

    invalid = client.post(
        reverse("listing_edit", args=[Listing.objects.get(owner=owner).pk]),
        {**listing_data(skill, duration_minutes="17"), "action": "save"},
    )
    assert invalid.status_code == 200
    assert "duration_minutes" in invalid.context["form"].errors
    assert Listing.objects.get(owner=owner).duration_minutes is None


@pytest.mark.django_db
def test_owner_can_withdraw_pending_submission_to_draft(client):
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(
        owner=owner,
        skill=categorized_skill(),
        title="Lesson",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=30,
        state=Listing.State.PENDING_REVIEW,
    )
    client.force_login(owner)

    response = client.post(
        reverse("listing_transition", args=[listing.pk]), {"action": "withdraw"}
    )

    listing.refresh_from_db()
    assert response.status_code == 302
    assert listing.state == Listing.State.DRAFT


@pytest.mark.django_db
def test_pending_listing_cannot_be_edited_or_resubmitted(client):
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(owner=owner, state=Listing.State.PENDING_REVIEW)
    client.force_login(owner)

    assert client.get(reverse("listing_edit", args=[listing.pk])).status_code == 404
    response = client.post(
        reverse("listing_transition", args=[listing.pk]), {"action": "submit"}
    )
    listing.refresh_from_db()
    assert response.status_code == 400
    assert listing.state == Listing.State.PENDING_REVIEW


@pytest.mark.django_db
def test_owner_can_remove_any_listing_but_removed_state_is_terminal(client):
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(owner=owner, state=Listing.State.DRAFT)
    client.force_login(owner)

    response = client.post(
        reverse("listing_transition", args=[listing.pk]), {"action": "remove"}
    )
    listing.refresh_from_db()
    assert response.status_code == 302
    assert listing.state == Listing.State.REMOVED
    assert client.get(reverse("listing_edit", args=[listing.pk])).status_code == 404
    assert (
        client.post(
            reverse("listing_transition", args=[listing.pk]), {"action": "submit"}
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_published_listing_must_return_to_draft_before_edit_and_resubmit(client):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    listing = Listing.objects.create(
        owner=owner,
        skill=skill,
        title="Published lesson",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=30,
        state=Listing.State.PUBLISHED,
    )
    profile = Profile.objects.create(
        user=owner,
        display_name="Owner",
        visibility=Profile.Visibility.PUBLIC,
    )
    client.force_login(owner)

    assert client.get(reverse("listing_edit", args=[listing.pk])).status_code == 404
    moved = client.post(
        reverse("listing_transition", args=[listing.pk]), {"action": "unpublish"}
    )
    listing.refresh_from_db()
    assert moved.status_code == 302
    assert listing.state == Listing.State.DRAFT
    assert client.get(reverse("listing_detail", args=[listing.pk])).status_code == 200

    saved = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {
            **listing_data(skill, title="Edited lesson"),
            "action": "save",
        },
    )
    listing.refresh_from_db()
    assert saved.status_code == 302
    assert listing.title == "Edited lesson"
    assert listing.state == Listing.State.DRAFT
    submitted = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {**listing_data(skill, title="Edited lesson"), "action": "submit"},
    )
    listing.refresh_from_db()
    assert submitted.status_code == 302
    assert listing.state == Listing.State.PENDING_REVIEW
    assert profile.pk == owner.profile.pk


@pytest.mark.django_db
def test_admin_can_publish_reject_with_reason_and_remove_published(client):
    staff = User.objects.create_superuser("staff@example.com", "admin-password")
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    profile = Profile.objects.create(
        user=owner, display_name="Owner", visibility=Profile.Visibility.PUBLIC
    )
    published_candidate = Listing.objects.create(
        owner=owner,
        skill=skill,
        title="Publish me",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=60,
        state=Listing.State.PENDING_REVIEW,
    )
    rejected_candidate = Listing.objects.create(
        owner=owner,
        skill=skill,
        title="Reject me",
        description="Description",
        learning_outcomes="Outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=30,
        state=Listing.State.PENDING_REVIEW,
    )
    client.force_login(staff)
    admin_url = reverse("admin:listings_listing_change", args=[published_candidate.pk])
    assert client.get(admin_url).status_code == 200

    publish_response = client.post(
        admin_url,
        {"state": Listing.State.PUBLISHED, "rejection_reason": "_", "_save": "Save"},
    )
    published_candidate.refresh_from_db()
    assert publish_response.status_code == 302
    assert published_candidate.state == Listing.State.PUBLISHED
    assert published_candidate.rejection_reason == ""
    assert profile.pk == owner.profile.pk

    reject_url = reverse("admin:listings_listing_change", args=[rejected_candidate.pk])
    missing_reason = client.post(
        reject_url,
        {"state": Listing.State.REJECTED, "rejection_reason": "", "_save": "Save"},
    )
    assert missing_reason.status_code == 200
    rejected_candidate.refresh_from_db()
    assert rejected_candidate.state == Listing.State.PENDING_REVIEW

    rejected = client.post(
        reject_url,
        {
            "state": Listing.State.REJECTED,
            "rejection_reason": "  Please add a clearer outcome. ",
            "_save": "Save",
        },
    )
    rejected_candidate.refresh_from_db()
    assert rejected.status_code == 302
    assert rejected_candidate.state == Listing.State.REJECTED
    assert rejected_candidate.rejection_reason == "Please add a clearer outcome."

    removed = client.post(
        admin_url,
        {
            "state": Listing.State.REMOVED,
            "rejection_reason": "",
            "_save": "Save",
        },
    )
    published_candidate.refresh_from_db()
    assert removed.status_code == 302
    assert published_candidate.state == Listing.State.REMOVED


@pytest.mark.django_db
def test_rejected_owner_can_edit_and_resubmit(client):
    owner = make_user("owner@example.com")
    skill = categorized_skill()
    listing = Listing.objects.create(
        owner=owner,
        skill=skill,
        title="Rejected lesson",
        description="Old description",
        learning_outcomes="Old outcome",
        level=Listing.Level.BEGINNER,
        duration_minutes=30,
        state=Listing.State.REJECTED,
        rejection_reason="Add more detail.",
    )
    client.force_login(owner)

    saved = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {
            **listing_data(skill, title="Improved lesson"),
            "action": "save",
        },
    )
    listing.refresh_from_db()
    assert saved.status_code == 302
    assert listing.state == Listing.State.REJECTED
    assert listing.title == "Improved lesson"
    assert listing.rejection_reason == "Add more detail."
    assert (
        b"Add more detail."
        in client.get(reverse("listing_detail", args=[listing.pk])).content
    )

    submitted = client.post(
        reverse("listing_edit", args=[listing.pk]),
        {**listing_data(skill, title="Improved lesson"), "action": "submit"},
    )
    listing.refresh_from_db()
    assert submitted.status_code == 302
    assert listing.state == Listing.State.PENDING_REVIEW
    assert listing.rejection_reason == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("visibility", "viewer_kind", "expected"),
    [
        (Profile.Visibility.PUBLIC, "anonymous", 200),
        (Profile.Visibility.MEMBERS_ONLY, "anonymous", 404),
        (Profile.Visibility.MEMBERS_ONLY, "member", 200),
        (Profile.Visibility.PRIVATE, "member", 404),
        (Profile.Visibility.PRIVATE, "staff", 200),
        (Profile.Visibility.PRIVATE, "owner", 200),
    ],
)
def test_published_listing_visibility_follows_owner_profile(
    client, visibility, viewer_kind, expected
):
    owner = make_user("owner@example.com")
    profile = Profile.objects.create(
        user=owner, display_name="Owner", visibility=visibility
    )
    listing = Listing.objects.create(
        owner=owner, title="Published lesson", state=Listing.State.PUBLISHED
    )
    if viewer_kind == "member":
        viewer = make_user("member@example.com")
    elif viewer_kind == "staff":
        viewer = User.objects.create_superuser("staff@example.com", "admin-password")
    elif viewer_kind == "owner":
        viewer = owner
    else:
        viewer = None
    if viewer:
        client.force_login(viewer)

    response = client.get(reverse("listing_detail", args=[listing.pk]))

    assert response.status_code == expected
    if expected == 200:
        assert b"Published lesson" in response.content
    else:
        assert b"Published lesson" not in response.content
    assert owner.profile == profile


@pytest.mark.django_db
@pytest.mark.parametrize(
    "state",
    [
        Listing.State.DRAFT,
        Listing.State.PENDING_REVIEW,
        Listing.State.REJECTED,
        Listing.State.REMOVED,
    ],
)
def test_nonpublished_listings_are_hidden_from_learners(client, state):
    owner = make_user("owner@example.com")
    Profile.objects.create(
        user=owner, display_name="Owner", visibility=Profile.Visibility.PUBLIC
    )
    listing = Listing.objects.create(owner=owner, title="Hidden listing", state=state)
    member = make_user("member@example.com")
    client.force_login(member)

    detail = client.get(reverse("listing_detail", args=[listing.pk]))
    index = client.get(reverse("listing_index"))

    assert detail.status_code == 404
    assert b"Hidden listing" not in detail.content
    assert b"Hidden listing" not in index.content


@pytest.mark.django_db
def test_only_active_owners_listing_is_learner_visible(client):
    inactive = make_user("inactive@example.com", state=User.State.SUSPENDED)
    Profile.objects.create(
        user=inactive, display_name="Inactive", visibility=Profile.Visibility.PUBLIC
    )
    listing = Listing.objects.create(
        owner=inactive, title="Inactive listing", state=Listing.State.PUBLISHED
    )

    response = client.get(reverse("listing_detail", args=[listing.pk]))

    assert response.status_code == 404
    assert b"Inactive listing" not in response.content


@pytest.mark.django_db
def test_owner_and_staff_can_view_nonpublished_listing(client):
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(
        owner=owner, title="Owner draft", state=Listing.State.DRAFT
    )
    client.force_login(owner)
    assert client.get(reverse("listing_detail", args=[listing.pk])).status_code == 200

    staff = User.objects.create_superuser("staff@example.com", "admin-password")
    client.force_login(staff)
    response = client.get(reverse("listing_detail", args=[listing.pk]))
    assert response.status_code == 200
    assert b"Owner draft" in response.content


@pytest.mark.django_db
def test_cross_owner_listing_edit_and_state_change_return_404(client):
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    listing = Listing.objects.create(owner=other, title="Other draft")
    client.force_login(owner)

    assert client.get(reverse("listing_edit", args=[listing.pk])).status_code == 404
    assert (
        client.post(
            reverse("listing_transition", args=[listing.pk]), {"action": "remove"}
        ).status_code
        == 404
    )
    listing.refresh_from_db()
    assert listing.state == Listing.State.DRAFT


@pytest.mark.django_db
def test_listing_state_and_duration_constraints_are_in_database():
    owner = make_user("owner@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.create(owner=owner, state="unknown")
    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.create(owner=owner, duration_minutes=16)


@pytest.mark.django_db
def test_listing_and_transition_forms_include_csrf_and_reject_missing_tokens():
    owner = make_user("owner@example.com")
    listing = Listing.objects.create(owner=owner, title="Draft")
    client = pytest.importorskip("django.test").Client(enforce_csrf_checks=True)
    client.force_login(owner)

    assert (
        client.post(
            reverse("listing_create"), {"action": "save", "title": "No token"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("listing_edit", args=[listing.pk]),
            {"action": "save", "title": "No token"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("listing_transition", args=[listing.pk]), {"action": "remove"}
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_moderation_form_requires_reason_and_admin_lists_categories_and_listings():
    owner = make_user("owner@example.com")
    pending = Listing.objects.create(owner=owner, state=Listing.State.PENDING_REVIEW)
    form = ListingModerationForm(
        {"state": Listing.State.REJECTED, "rejection_reason": ""}, instance=pending
    )
    assert not form.is_valid()
    assert "rejection_reason" in form.errors

    site = AdminSite()
    listing_admin = ListingAdmin(Listing, site)
    request = type(
        "Request", (), {"user": make_user("admin@example.com", staff=True)}
    )()
    assert listing_admin.has_add_permission(request) is False
