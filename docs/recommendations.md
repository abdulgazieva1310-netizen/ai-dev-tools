# Recommendations

`listings.recommendations.recommend_listings` builds the homepage
recommendation list. It is HTTP-independent: it takes the learner
(a user, `AnonymousUser`, or `None`), an explicit iterable of followed teacher
user IDs, and a result limit (default `10`), and returns an ordered list of
`Listing` objects. It can be called directly in tests without a request object.

## Eligibility

A listing can only be recommended when all of the following hold:

- `listing.state == Listing.State.PUBLISHED` (drafts, pending review, rejected,
  and removed listings never appear);
- the owner is active;
- the owner has a `Profile` that is visible to the learner according to
  `profiles.views.profile_visible_to` (owners without a profile and invisible
  profiles never appear);
- the listing does not belong to the learner.

Followed teacher IDs that are unknown, inactive, or the learner's own ID are
ignored and cannot contribute the followed-teacher signal.

## Weights

Each signal is added at most once per listing:

| Signal | Weight | Condition |
| --- | --- | --- |
| Wanted skill | `+5` | The learner's profile has a `ProfileSkill(skill=listing.skill, intent=WANTS_TO_LEARN)`. |
| Level | `+2` | That same wanted `ProfileSkill`'s `level` equals `listing.level`. A blank `listing.level` earns no level points. |
| Shared language | `+1` | The owner's profile `languages` shares at least one label (trimmed, case-insensitive) with the learner's profile `languages`. |
| Followed teacher | `+3` | `listing.owner_id` is in the valid followed teacher IDs. |

## Ordering

Results are ordered by total score descending, then `title` ascending, then
`pk` ascending. Ordering is deterministic and stable; no popularity, rating,
review, or wall-clock recency signal is used.

## Diversity

The returned results are treated as consecutive blocks of up to ten.

- No single owner appears more than three times in a block.
- Each block contains at most one listing from a given teacher with fewer than
  three published listings (counted across all of that owner's published
  listings).
- Each block reserves at most one slot for an eligible teacher with fewer than
  three published listings. When such a teacher has an eligible listing, one is
  included in the block even though a higher-ranked repeat would otherwise fill
  the list.

## Cold start

When the learner is anonymous, or has no wanted skills and no shared-language
data, the same scoring and tie-break apply (scores may all be zero) and a
diverse eligible list is still returned. The function returns an empty list
only when no listing is eligible.
