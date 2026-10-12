from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q

from listings.models import Category, Listing
from profiles.models import Profile, Skill
from profiles.views import profile_visible_to

PAGE_SIZE = 10


def visible_owner_ids(viewer):
    profiles = Profile.objects.select_related("user").all()
    return [
        profile.user_id
        for profile in profiles
        if profile.user.is_active and profile_visible_to(profile, viewer)
    ]


def search_listings(params, viewer):
    term = params.get("q", "").strip()
    queryset = Listing.objects.filter(
        state=Listing.State.PUBLISHED,
        owner_id__in=visible_owner_ids(viewer),
    ).select_related(
        "owner", "owner__profile", "skill", "skill__category_assignment__category"
    )

    category_value = params.get("category", "").strip()
    skill_value = params.get("skill", "").strip()
    if category_value:
        if (
            not category_value.isdecimal()
            or not Category.objects.filter(pk=category_value).exists()
        ):
            queryset = queryset.none()
        else:
            queryset = queryset.filter(
                skill__category_assignment__category_id=category_value
            )
    if skill_value:
        if (
            not skill_value.isdecimal()
            or not Skill.objects.filter(pk=skill_value).exists()
        ):
            queryset = queryset.none()
        else:
            queryset = queryset.filter(skill_id=skill_value)

    listing_type = params.get("type", "").strip()
    if listing_type:
        if listing_type not in Listing.Type.values:
            queryset = queryset.none()
        else:
            queryset = queryset.filter(listing_type=listing_type)

    level = params.get("level", "").strip()
    if level:
        if level not in Listing.Level.values:
            queryset = queryset.none()
        else:
            queryset = queryset.filter(level=level)

    language = params.get("language", "").strip().casefold()
    if language:
        matching_owner_ids = [
            profile.user_id
            for profile in Profile.objects.filter(user_id__in=visible_owner_ids(viewer))
            if any(language == value.strip().casefold() for value in profile.languages)
        ]
        queryset = queryset.filter(owner_id__in=matching_owner_ids)

    if term:
        if connection.vendor == "postgresql":
            vector = SearchVector(
                "title", "description", "learning_outcomes", config="simple"
            )
            query = SearchQuery(term, config="simple")
            queryset = (
                queryset.annotate(search=vector, rank=SearchRank(vector, query))
                .filter(search=query)
                .order_by("-rank", "title", "pk")
            )
        else:
            text_query = (
                Q(title__icontains=term)
                | Q(description__icontains=term)
                | Q(learning_outcomes__icontains=term)
            )
            queryset = queryset.filter(text_query).order_by("title", "pk")
    else:
        queryset = queryset.order_by("title", "pk")

    paginator = Paginator(queryset, PAGE_SIZE)
    page = paginator.get_page(params.get("page", "1"))
    return page, {
        "categories": Category.objects.order_by("name", "pk"),
        "skills": Skill.objects.filter(category_assignment__isnull=False).order_by(
            "name", "pk"
        ),
        "types": Listing.Type.choices,
        "levels": Listing.Level.choices,
        "selected": {
            "q": params.get("q", ""),
            "category": category_value,
            "skill": skill_value,
            "type": listing_type,
            "level": level,
            "language": params.get("language", ""),
        },
    }
