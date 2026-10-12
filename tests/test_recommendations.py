import pytest
from django.contrib.auth.models import AnonymousUser

from accounts.models import User
from listings.models import Listing
from listings.recommendations import recommend_listings
from profiles.models import Profile, ProfileSkill, Skill


def make_user(email, *, state=User.State.ACTIVE, staff=False):
    return User.objects.create_user(
        email,
        password="recommendations-test-password",
        state=state,
        is_staff=staff,
    )


def make_profile(user, *, visibility=Profile.Visibility.PUBLIC, languages=None):
    return Profile.objects.create(
        user=user,
        display_name=user.email,
        languages=languages or [],
        visibility=visibility,
    )


def make_listing(
    owner,
    title,
    *,
    skill=None,
    level="",
    state=Listing.State.PUBLISHED,
):
    return Listing.objects.create(
        owner=owner,
        skill=skill,
        title=title,
        level=level,
        state=state,
    )


def want(profile, skill, level):
    return ProfileSkill.objects.create(
        profile=profile,
        skill=skill,
        intent=ProfileSkill.Intent.WANTS_TO_LEARN,
        level=level,
    )


@pytest.mark.django_db
def test_wanted_skill_match_is_the_strongest_single_signal():
    learner = make_user("learner@example.com")
    profile = make_profile(learner)
    python = Skill.objects.create(name="Python")
    django = Skill.objects.create(name="Django")
    want(profile, python, ProfileSkill.Level.BEGINNER)

    matched_owner = make_user("matched@example.com")
    make_profile(matched_owner)
    unmatched_owner = make_user("unmatched@example.com")
    make_profile(unmatched_owner)
    matched = make_listing(
        matched_owner,
        "Matched",
        skill=python,
        level=ProfileSkill.Level.ADVANCED,
    )
    unmatched = make_listing(
        unmatched_owner,
        "Unmatched",
        skill=django,
        level=ProfileSkill.Level.ADVANCED,
    )

    result = recommend_listings(learner, [], limit=10)

    assert result == [matched, unmatched]


@pytest.mark.django_db
def test_matching_level_adds_points_on_top_of_the_skill_match():
    learner = make_user("learner@example.com")
    profile = make_profile(learner)
    python = Skill.objects.create(name="Python")
    want(profile, python, ProfileSkill.Level.BEGINNER)

    matching_owner = make_user("matching@example.com")
    make_profile(matching_owner)
    other_owner = make_user("other@example.com")
    make_profile(other_owner)
    # Lower title so the level bonus is the only reason it ranks first.
    matching = make_listing(
        matching_owner,
        "Bravo",
        skill=python,
        level=ProfileSkill.Level.BEGINNER,
    )
    advanced = make_listing(
        other_owner,
        "Alpha",
        skill=python,
        level=ProfileSkill.Level.ADVANCED,
    )

    result = recommend_listings(learner, [], limit=10)

    assert result == [matching, advanced]


@pytest.mark.django_db
def test_blank_listing_level_earns_no_level_points():
    learner = make_user("learner@example.com")
    profile = make_profile(learner)
    python = Skill.objects.create(name="Python")
    # The learner's only wanted level is blank-incompatible, so a blank
    # listing level must not match any level.
    ProfileSkill.objects.create(
        profile=profile,
        skill=python,
        intent=ProfileSkill.Intent.WANTS_TO_LEARN,
        level=ProfileSkill.Level.INTERMEDIATE,
    )

    blank_owner = make_user("blank@example.com")
    make_profile(blank_owner)
    blank = make_listing(blank_owner, "Alpha", skill=python, level="")

    result = recommend_listings(learner, [], limit=10)

    assert result == [blank]


@pytest.mark.django_db
def test_shared_language_adds_points_case_insensitively_and_trimmed():
    learner = make_user("learner@example.com")
    make_profile(learner, languages=["English"])

    shared_owner = make_user("shared@example.com")
    make_profile(shared_owner, languages=["  english  "])
    other_owner = make_user("other@example.com")
    make_profile(other_owner, languages=["French"])
    shared = make_listing(shared_owner, "Zulu")
    other = make_listing(other_owner, "Alpha")

    result = recommend_listings(learner, [], limit=10)

    assert result == [shared, other]


@pytest.mark.django_db
def test_followed_teacher_adds_points():
    learner = make_user("learner@example.com")
    make_profile(learner)

    followed_owner = make_user("followed@example.com")
    make_profile(followed_owner)
    other_owner = make_user("other@example.com")
    make_profile(other_owner)
    followed = make_listing(followed_owner, "Zulu")
    other = make_listing(other_owner, "Alpha")

    result = recommend_listings(learner, [followed_owner.pk], limit=10)

    assert result == [followed, other]


@pytest.mark.django_db
def test_all_four_signals_accumulate_into_one_total():
    learner = make_user("learner@example.com")
    profile = make_profile(learner, languages=["English"])
    python = Skill.objects.create(name="Python")
    want(profile, python, ProfileSkill.Level.BEGINNER)

    full_owner = make_user("full@example.com")
    make_profile(full_owner, languages=["English"])
    partial_owner = make_user("partial@example.com")
    make_profile(partial_owner, languages=["French"])
    zero_owner = make_user("zero@example.com")
    make_profile(zero_owner)

    full = make_listing(
        full_owner, "Full", skill=python, level=ProfileSkill.Level.BEGINNER
    )
    partial = make_listing(
        partial_owner, "Partial", skill=python, level=ProfileSkill.Level.BEGINNER
    )
    zero = make_listing(zero_owner, "Zero")

    result = recommend_listings(learner, [full_owner.pk], limit=10)

    assert result == [full, partial, zero]


@pytest.mark.django_db
def test_score_ties_are_broken_by_title_then_primary_key():
    first_owner = make_user("first@example.com")
    make_profile(first_owner)
    second_owner = make_user("second@example.com")
    make_profile(second_owner)

    bravo = make_listing(first_owner, "Bravo")
    alpha = make_listing(second_owner, "Alpha")

    result = recommend_listings(AnonymousUser(), [], limit=10)

    assert result == [alpha, bravo]


@pytest.mark.django_db
def test_identical_titles_are_broken_by_primary_key():
    first_owner = make_user("first@example.com")
    make_profile(first_owner)
    second_owner = make_user("second@example.com")
    make_profile(second_owner)

    earliest = make_listing(first_owner, "Same title")
    latest = make_listing(second_owner, "Same title")

    result = recommend_listings(AnonymousUser(), [], limit=10)

    assert result == [earliest, latest]


@pytest.mark.django_db
def test_anonymous_cold_start_returns_a_diverse_eligible_list():
    for index in range(3):
        owner = make_user(f"owner-{index}@example.com")
        make_profile(owner)
        make_listing(owner, f"Lesson {index}")

    result = recommend_listings(AnonymousUser(), [], limit=10)

    assert [listing.title for listing in result] == [
        "Lesson 0",
        "Lesson 1",
        "Lesson 2",
    ]


@pytest.mark.django_db
def test_learner_without_preferences_gets_the_same_cold_start_fallback():
    learner = make_user("learner@example.com")
    make_profile(learner)
    owner = make_user("owner@example.com")
    make_profile(owner)
    listing = make_listing(owner, "Only lesson")

    assert recommend_listings(learner, [], limit=10) == [listing]
    assert recommend_listings(None, [], limit=10) == [listing]


@pytest.mark.django_db
def test_owner_cap_limits_repeats_within_a_block():
    prolific = make_user("prolific@example.com")
    make_profile(prolific)
    for index in range(6):
        make_listing(prolific, f"A{index}")

    others = []
    for index in range(7):
        owner = make_user(f"other-{index}@example.com")
        make_profile(owner)
        others.append(make_listing(owner, f"B{index}"))

    result = recommend_listings(AnonymousUser(), [], limit=10)

    assert len(result) == 10
    prolific_count = sum(1 for listing in result if listing.owner_id == prolific.pk)
    assert prolific_count == 3


@pytest.mark.django_db
def test_new_teacher_reserved_slot_displaces_a_repeated_owner():
    for group in "ABCD":
        owner = make_user(f"{group.lower()}-owner@example.com")
        make_profile(owner)
        for index in range(3):
            make_listing(owner, f"{group}{index}")

    newcomer = make_user("newcomer@example.com")
    make_profile(newcomer)
    reserved = make_listing(newcomer, "Zzz reserved")

    result = recommend_listings(AnonymousUser(), [], limit=10)

    assert len(result) == 10
    assert reserved in result
    # The reserved listing is the only entry from the new teacher.
    assert sum(1 for listing in result if listing.owner_id == newcomer.pk) == 1


@pytest.mark.django_db
def test_learner_own_listings_are_excluded_even_when_followed():
    learner = make_user("learner@example.com")
    make_profile(learner)
    make_listing(learner, "My own lesson")

    assert recommend_listings(learner, [learner.pk], limit=10) == []


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
def test_unpublished_listings_are_never_recommended(state):
    owner = make_user("owner@example.com")
    make_profile(owner)
    make_listing(owner, "Hidden lesson", state=state)

    assert recommend_listings(AnonymousUser(), [], limit=10) == []


@pytest.mark.django_db
def test_owners_without_a_visible_profile_are_excluded():
    no_profile_owner = make_user("no-profile@example.com")
    make_listing(no_profile_owner, "No profile")

    private_owner = make_user("private@example.com")
    make_profile(private_owner, visibility=Profile.Visibility.PRIVATE)
    make_listing(private_owner, "Private profile")

    inactive_owner = make_user("inactive@example.com", state=User.State.SUSPENDED)
    make_profile(inactive_owner)
    make_listing(inactive_owner, "Inactive owner")

    members_owner = make_user("members@example.com")
    make_profile(members_owner, visibility=Profile.Visibility.MEMBERS_ONLY)
    members_listing = make_listing(members_owner, "Members only")

    assert recommend_listings(AnonymousUser(), [], limit=10) == []

    learner = make_user("learner@example.com")
    make_profile(learner)
    assert recommend_listings(learner, [], limit=10) == [members_listing]


@pytest.mark.django_db
def test_unknown_inactive_and_self_followed_ids_are_ignored():
    learner = make_user("learner@example.com")
    make_profile(learner)
    inactive = make_user("inactive@example.com", state=User.State.SUSPENDED)
    make_profile(inactive)
    make_listing(inactive, "Inactive listing")

    followed_owner = make_user("followed@example.com")
    make_profile(followed_owner)
    followed_listing = make_listing(followed_owner, "Followed")
    other_owner = make_user("other@example.com")
    make_profile(other_owner)
    other_listing = make_listing(other_owner, "Other")

    ignored = recommend_listings(
        learner, [987654321, learner.pk, inactive.pk], limit=10
    )
    assert ignored == [followed_listing, other_listing]

    counted = recommend_listings(learner, [followed_owner.pk], limit=10)
    assert counted[0] == followed_listing


@pytest.mark.django_db
def test_limit_controls_the_number_of_results():
    for index in range(4):
        owner = make_user(f"owner-{index}@example.com")
        make_profile(owner)
        make_listing(owner, f"Lesson {index}")

    assert len(recommend_listings(AnonymousUser(), [], limit=2)) == 2
    assert recommend_listings(AnonymousUser(), [], limit=0) == []


@pytest.mark.django_db
def test_empty_list_when_no_listing_is_eligible():
    assert recommend_listings(AnonymousUser(), [], limit=10) == []
    assert recommend_listings(None, [], limit=10) == []
