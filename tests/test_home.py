import pytest
from django.urls import reverse

from accounts.models import User
from listings.models import Listing
from profiles.models import Profile


@pytest.mark.django_db
def test_home_page_returns_expected_content(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert b"<h1>SkillSwap</h1>" in response.content
    assert b'id="recommendations-heading"' in response.content


@pytest.mark.django_db
def test_home_shows_empty_state_when_no_listing_is_eligible(client):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"No recommendations yet." in response.content


@pytest.mark.django_db
def test_home_lists_up_to_five_recommendations_linked_to_their_detail(client):
    listings = []
    for index in range(6):
        owner = User.objects.create_user(
            f"owner-{index}@example.com", password="home-password"
        )
        Profile.objects.create(
            user=owner, display_name="Owner", visibility=Profile.Visibility.PUBLIC
        )
        # Three published listings keep each owner out of the new-teacher pool,
        # whose single reserved slot would otherwise cap the homepage list.
        for extra in range(3):
            listings.append(
                Listing.objects.create(
                    owner=owner,
                    title=f"Lesson {index}-{extra}",
                    state=Listing.State.PUBLISHED,
                )
            )

    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert b"No recommendations yet." not in response.content
    shown = [
        listing for listing in listings if listing.title.encode() in response.content
    ]
    assert len(shown) == 5
    for listing in shown:
        detail_url = reverse("listing_detail", args=[listing.pk]).encode()
        assert detail_url in response.content
