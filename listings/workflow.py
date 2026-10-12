from django.core.exceptions import ValidationError

from listings.models import Listing


def transition_owner_listing(listing, actor, action):
    if not actor.is_active or listing.owner_id != actor.pk:
        raise ValidationError("Only the active listing owner can change this listing.")
    if listing.state == Listing.State.REMOVED:
        raise ValidationError("Removed listings cannot be changed.")

    if action == "submit":
        if listing.state not in (Listing.State.DRAFT, Listing.State.REJECTED):
            raise ValidationError("Only a draft or rejected listing can be submitted.")
        if actor.email_verified_at is None:
            raise ValidationError(
                "Verify your email before submitting a listing for review."
            )
        listing.validate_complete()
        listing.state = Listing.State.PENDING_REVIEW
        listing.rejection_reason = ""
    elif action == "withdraw" and listing.state == Listing.State.PENDING_REVIEW:
        listing.state = Listing.State.DRAFT
    elif action == "unpublish" and listing.state == Listing.State.PUBLISHED:
        listing.state = Listing.State.DRAFT
    elif action == "remove":
        listing.state = Listing.State.REMOVED
    else:
        raise ValidationError("That listing state change is not allowed.")
    listing.save()
    return listing


def transition_staff_listing(listing, target, rejection_reason=""):
    if listing.state == Listing.State.PENDING_REVIEW and target in (
        Listing.State.PUBLISHED,
        Listing.State.REJECTED,
    ):
        if target == Listing.State.PUBLISHED:
            listing.validate_complete()
        if target == Listing.State.REJECTED and not rejection_reason.strip():
            raise ValidationError("A rejection reason is required.")
        listing.state = target
        listing.rejection_reason = (
            rejection_reason.strip() if target == Listing.State.REJECTED else ""
        )
    elif listing.state == Listing.State.PUBLISHED and target == Listing.State.REMOVED:
        listing.state = Listing.State.REMOVED
        listing.rejection_reason = ""
    elif target != listing.state:
        raise ValidationError("That staff listing state change is not allowed.")
    listing.save()
    return listing
