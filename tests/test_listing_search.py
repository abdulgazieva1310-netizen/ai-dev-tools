import os
import sys

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.urls import reverse

from accounts.models import User
from listings.models import Category, Listing, SkillCategory
from listings.search import search_listings
from profiles.models import Profile, Skill


def create_listing(
    title,
    *,
    text="",
    level=Listing.Level.BEGINNER,
    language="English",
    state=Listing.State.PUBLISHED,
    visibility=Profile.Visibility.PUBLIC,
    owner_email=None,
    listing_type=Listing.Type.LIVE,
):
    owner_email = owner_email or f"{title.lower().replace(' ', '-')}-owner@example.com"
    owner = User.objects.create_user(
        owner_email, password="search-test-password", email_verified_at=None
    )
    Profile.objects.create(
        user=owner,
        display_name=title,
        languages=[language],
        visibility=visibility,
    )
    skill, _ = Skill.objects.get_or_create(name="Python")
    category, _ = Category.objects.get_or_create(name="Programming")
    SkillCategory.objects.get_or_create(skill=skill, defaults={"category": category})
    return Listing.objects.create(
        owner=owner,
        skill=skill,
        title=title,
        description=text,
        learning_outcomes=text,
        level=level,
        duration_minutes=30,
        listing_type=listing_type,
        state=state,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["title", "description", "learning_outcomes"])
def test_search_matches_each_text_field(client, field):
    if field == "title":
        listing = create_listing("Needle lesson")
    elif field == "description":
        listing = create_listing("Description lesson", text="needle appears here")
    else:
        listing = create_listing("Outcome lesson", text="needle appears here")
    response = client.get(reverse("listing_search"), {"q": "needle"})
    assert response.status_code == 200
    assert listing in response.context["page_obj"].object_list


@pytest.mark.django_db
def test_blank_term_and_composable_filters_and_invalid_values(client):
    matching = create_listing("Python beginner", level=Listing.Level.BEGINNER)
    advanced = create_listing("Python advanced", level=Listing.Level.ADVANCED)
    transcript = create_listing("Transcript item", listing_type=Listing.Type.TRANSCRIPT)
    spanish = create_listing("Spanish teacher", language="Spanish")
    filters = (
        ({"category": matching.category.pk}, {matching, advanced, transcript, spanish}),
        ({"skill": matching.skill_id}, {matching, advanced, transcript, spanish}),
        ({"type": "live"}, {matching, advanced, spanish}),
        ({"level": "beginner"}, {matching, transcript, spanish}),
        ({"language": "Spanish"}, {spanish}),
    )
    for params, expected in filters:
        response = client.get(reverse("listing_search"), params)
        assert set(response.context["page_obj"].object_list) == expected

    response = client.get(
        reverse("listing_search"),
        {
            "q": " ",
            "category": matching.category.pk,
            "skill": matching.skill_id,
            "type": "live",
            "level": "beginner",
            "language": "english",
        },
    )
    assert list(response.context["page_obj"].object_list) == [matching]
    for params in (
        {"category": "unknown"},
        {"skill": "-4"},
        {"type": "bogus"},
        {"level": "bogus"},
        {"language": "Klingon"},
    ):
        response = client.get(reverse("listing_search"), params)
        assert response.status_code == 200
        assert list(response.context["page_obj"].object_list) == []


@pytest.mark.django_db
def test_search_term_url_state_and_pagination(client):
    for index in range(12):
        create_listing(f"Alpha {index:02d}", text="common term")
    params = {"q": "common", "level": "beginner", "language": "English"}
    first = client.get(reverse("listing_search"), params)
    assert first.context["page_obj"].paginator.count == 12
    next_url = first.context["page_obj"].next_page_number()
    second = client.get(reverse("listing_search"), {**params, "page": next_url})
    assert second.context["selected"]["q"] == "common"
    assert "level=beginner" in second.context["pagination_query"]
    assert (
        list(first.context["page_obj"])[0].title
        < list(second.context["page_obj"])[0].title
    )


@pytest.mark.django_db
def test_search_visibility_and_unpublished_states(client):
    public = create_listing("Public result")
    private = create_listing("Private result", visibility=Profile.Visibility.PRIVATE)
    hidden_states = [
        Listing.State.DRAFT,
        Listing.State.PENDING_REVIEW,
        Listing.State.REJECTED,
        Listing.State.REMOVED,
    ]
    for index, state in enumerate(hidden_states):
        create_listing(f"Hidden {index}", state=state)
    result = client.get(reverse("listing_search"), {"q": "result"})
    assert list(result.context["page_obj"].object_list) == [public]
    assert private not in result.context["page_obj"].object_list

    member = User.objects.create_user("member@example.com", password="password")
    client.force_login(member)
    result = client.get(reverse("listing_search"), {"q": "result"})
    assert set(result.context["page_obj"].object_list) == {public}


@pytest.mark.django_db
def test_postgresql_full_text_rank_and_stable_ties():
    if (
        os.environ.get("RUN_POSTGRES_SEARCH_TESTS") == "1"
        or any(
            argument.endswith("tests/test_listing_search.py") for argument in sys.argv
        )
    ) and connection.vendor != "postgresql":
        pytest.fail("PostgreSQL search needs the Compose database; backend is SQLite.")
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL-specific assertions run in Docker Compose.")

    weak = create_listing("Alpha weak", text="shared phrase")
    weak.learning_outcomes = ""
    weak.save(update_fields=("learning_outcomes",))
    tie_one = create_listing("Beta tie", text="shared phrase")
    tie_two = create_listing("Gamma tie", text="shared phrase")
    strongest = create_listing("Shared phrase", text="shared phrase")
    title_match = create_listing("Zeta titleterm")
    description_match = create_listing("Eta description", text="descriptionterm")
    outcome_match = create_listing("Theta outcome", text="outcometerm")

    page, _ = search_listings({"q": "shared phrase"}, AnonymousUser())
    found = list(page.object_list)
    assert found[0] == strongest
    assert found.index(tie_one) < found.index(tie_two)
    assert found.index(tie_one) < found.index(weak)

    for term, expected in (
        ("titleterm", title_match),
        ("descriptionterm", description_match),
        ("outcometerm", outcome_match),
    ):
        page, _ = search_listings({"q": term}, AnonymousUser())
        assert expected in page.object_list
