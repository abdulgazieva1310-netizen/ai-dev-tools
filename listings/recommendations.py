from collections import Counter

from django.contrib.auth.models import AnonymousUser

from accounts.models import User
from listings.models import Listing
from listings.views import owner_can_see
from profiles.models import Profile, ProfileSkill

DEFAULT_LIMIT = 10
BLOCK_SIZE = 10
OWNER_BLOCK_CAP = 3
NEW_TEACHER_PUBLISHED_THRESHOLD = 3
NEW_TEACHER_BLOCK_CAP = 1

SKILL_MATCH_WEIGHT = 5
LEVEL_MATCH_WEIGHT = 2
SHARED_LANGUAGE_WEIGHT = 1
FOLLOWED_TEACHER_WEIGHT = 3


def recommend_listings(learner, followed_teacher_ids, limit=DEFAULT_LIMIT):
    """Rank published listings for a learner using explainable, deterministic rules.

    ``learner`` may be a user, ``AnonymousUser``, or ``None``. Importance is
    governed by wanted-skill, level, shared-language, and followed-teacher
    signals; diversity caps and a new-teacher reserved slot are applied per
    block of up to ten results. No request object is required.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if limit <= 0:
        return []

    viewer = learner if learner is not None else AnonymousUser()
    learner_id = _user_id(viewer)
    learner_profile = _profile_for(learner_id)
    wanted_skills = _wanted_skills(learner_profile)
    learner_languages = _language_labels(learner_profile)
    followed_ids = _valid_followed_ids(followed_teacher_ids, learner_id)

    profiles_by_user = {
        profile.user_id: profile for profile in Profile.objects.select_related("user")
    }
    published_counts = Counter(
        Listing.objects.filter(state=Listing.State.PUBLISHED).values_list(
            "owner_id", flat=True
        )
    )

    candidates = []
    listings = Listing.objects.filter(state=Listing.State.PUBLISHED).select_related(
        "owner", "skill"
    )
    for listing in listings:
        if not _eligible(listing, viewer, learner_id):
            continue
        score = _score(
            listing,
            wanted_skills,
            learner_languages,
            followed_ids,
            profiles_by_user,
        )
        candidates.append((score, listing))

    candidates.sort(key=lambda item: (-item[0], item[1].title, item[1].pk))
    ranked = [
        (index, score, listing) for index, (score, listing) in enumerate(candidates)
    ]

    pooled = _apply_diversity(ranked, limit, published_counts, learner_id)
    return [listing for _, _, listing in pooled]


def _user_id(viewer):
    if not getattr(viewer, "is_authenticated", False):
        return None
    return getattr(viewer, "pk", None)


def _profile_for(user_id):
    if user_id is None:
        return None
    return Profile.objects.filter(user_id=user_id).first()


def _wanted_skills(profile):
    if profile is None:
        return {}
    interests = ProfileSkill.objects.filter(
        profile=profile, intent=ProfileSkill.Intent.WANTS_TO_LEARN
    )
    return {interest.skill_id: interest.level for interest in interests}


def _language_labels(profile):
    if profile is None:
        return set()
    return {
        label.strip().casefold()
        for label in (profile.languages or [])
        if isinstance(label, str) and label.strip()
    }


def _valid_followed_ids(followed_teacher_ids, learner_id):
    ids = set(followed_teacher_ids or [])
    if not ids:
        return set()
    valid = set(
        User.objects.filter(pk__in=ids, state=User.State.ACTIVE).values_list(
            "pk", flat=True
        )
    )
    valid.discard(learner_id)
    return valid


def _eligible(listing, viewer, learner_id):
    if listing.owner_id == learner_id:
        return False
    return owner_can_see(listing, viewer)


def _score(listing, wanted_skills, learner_languages, followed_ids, profiles_by_user):
    score = 0
    wanted_level = wanted_skills.get(listing.skill_id)
    if wanted_level is not None:
        score += SKILL_MATCH_WEIGHT
        if listing.level and listing.level == wanted_level:
            score += LEVEL_MATCH_WEIGHT
    if learner_languages:
        owner_profile = profiles_by_user.get(listing.owner_id)
        if owner_profile and learner_languages & _language_labels(owner_profile):
            score += SHARED_LANGUAGE_WEIGHT
    if listing.owner_id in followed_ids:
        score += FOLLOWED_TEACHER_WEIGHT
    return score


def _apply_diversity(ranked, limit, published_counts, learner_id):
    result = []
    pool = list(ranked)
    while len(result) < limit and pool:
        capacity = min(BLOCK_SIZE, limit - len(result))
        block, pool = _select_block(pool, capacity, published_counts, learner_id)
        if not block:
            break
        if len(block) < capacity and pool:
            # A per-owner or new-teacher cap left this block short while
            # eligible listings still remain. Emitting the short block would
            # let the next block start early, so the fixed ten-result windows
            # of the final list would straddle block boundaries. Stop instead
            # and return only the fully aligned blocks.
            break
        result.extend(block)
    return result


def _select_block(pool, capacity, published_counts, learner_id):
    selected = []
    owner_counts = Counter()

    # At most one new-teacher listing per block. The highest-ranked eligible
    # new teacher takes the single reserved slot, even though a higher-ranked
    # established owner would otherwise fill the list.
    reserved = _reserved_new_teacher(pool, published_counts, learner_id)
    if reserved is not None:
        selected.append(reserved)
        owner_counts[reserved[2].owner_id] += 1

    for item in pool:
        if len(selected) >= capacity:
            break
        if item is reserved:
            continue
        owner_id = item[2].owner_id
        if owner_id == learner_id:
            continue
        if _is_new_teacher(owner_id, published_counts):
            # Only the single reserved new-teacher slot is available.
            continue
        if owner_counts[owner_id] >= OWNER_BLOCK_CAP:
            continue
        selected.append(item)
        owner_counts[owner_id] += 1

    if not selected:
        return [], pool

    selected.sort(key=lambda item: item[0])
    selected_ranks = {item[0] for item in selected}
    remaining = [item for item in pool if item[0] not in selected_ranks]
    return selected, remaining


def _reserved_new_teacher(pool, published_counts, learner_id):
    if NEW_TEACHER_BLOCK_CAP <= 0:
        return None
    for item in pool:
        owner_id = item[2].owner_id
        if owner_id == learner_id:
            continue
        if _is_new_teacher(owner_id, published_counts):
            return item
    return None


def _is_new_teacher(owner_id, published_counts):
    return published_counts.get(owner_id, 0) < NEW_TEACHER_PUBLISHED_THRESHOLD
