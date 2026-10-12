from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from listings.forms import ListingForm
from listings.models import Listing
from listings.search import search_listings
from listings.workflow import transition_owner_listing
from profiles.models import Profile
from profiles.views import profile_visible_to


def owner_can_see(listing, viewer):
    if listing.state != Listing.State.PUBLISHED or not listing.owner.is_active:
        return False
    profile = Profile.objects.filter(user_id=listing.owner_id).first()
    return bool(profile and profile_visible_to(profile, viewer))


def listing_visible_to(listing, viewer):
    if viewer.is_authenticated and viewer.pk == listing.owner_id:
        return True
    if viewer.is_authenticated and viewer.is_active and viewer.is_staff:
        return True
    return owner_can_see(listing, viewer)


@require_http_methods(["GET"])
def listing_index(request):
    candidates = (
        Listing.objects.filter(state=Listing.State.PUBLISHED)
        .select_related("owner", "skill", "skill__category_assignment__category")
        .order_by("title", "pk")
    )
    visible = [
        listing for listing in candidates if owner_can_see(listing, request.user)
    ]
    return render(request, "listings/listing_index.html", {"listings": visible})


@require_http_methods(["GET"])
def listing_search(request):
    page, context = search_listings(request.GET, request.user)
    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "listings/listing_search.html",
        {**context, "page_obj": page, "pagination_query": query.urlencode()},
    )


@require_http_methods(["GET"])
def listing_detail(request, listing_id):
    listing = get_object_or_404(
        Listing.objects.select_related(
            "owner", "skill", "skill__category_assignment__category"
        ),
        pk=listing_id,
    )
    if not listing_visible_to(listing, request.user):
        raise Http404
    is_owner = request.user.is_authenticated and request.user.pk == listing.owner_id
    is_staff_viewer = (
        request.user.is_authenticated
        and request.user.is_active
        and request.user.is_staff
    )
    return render(
        request,
        "listings/listing_detail.html",
        {
            "listing": listing,
            "is_owner": is_owner,
            "is_staff_viewer": is_staff_viewer,
        },
    )


def listing_form_response(request, listing=None):
    if not request.user.is_active:
        raise Http404
    form = ListingForm(
        request.POST if request.method == "POST" else None, instance=listing
    )
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action not in {"save", "submit"}:
            form.add_error(None, "Choose whether to save a draft or submit it.")
        elif form.is_valid():
            candidate = form.save(commit=False)
            candidate.owner = request.user
            if action == "submit":
                if request.user.email_verified_at is None:
                    form.add_error(
                        None, "Verify your email before submitting for review."
                    )
                else:
                    form.validate_for_submission(candidate)
            if not form.errors:
                try:
                    with transaction.atomic():
                        if action == "submit":
                            transition_owner_listing(candidate, request.user, "submit")
                        else:
                            candidate.save()
                except ValidationError as error:
                    if hasattr(error, "error_dict"):
                        for field, errors in error.error_dict.items():
                            for item in errors:
                                form.add_error(
                                    field if field in form.fields else None, item
                                )
                    else:
                        form.add_error(None, error)
                else:
                    return redirect("listing_detail", listing_id=candidate.pk)
    return render(
        request,
        "listings/listing_form.html",
        {
            "form": form,
            "listing": listing,
            "heading": "Edit listing" if listing else "Create a live lesson",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def listing_create(request):
    return listing_form_response(request)


@login_required
@require_http_methods(["GET", "POST"])
def listing_edit(request, listing_id):
    if not request.user.is_active:
        raise Http404
    listing = get_object_or_404(
        Listing,
        pk=listing_id,
        owner=request.user,
        state__in=(Listing.State.DRAFT, Listing.State.REJECTED),
    )
    return listing_form_response(request, listing)


@login_required
@require_POST
def listing_transition(request, listing_id):
    if not request.user.is_active:
        raise Http404
    action = request.POST.get("action", "")
    try:
        with transaction.atomic():
            listing = get_object_or_404(
                Listing.objects.select_for_update(),
                pk=listing_id,
                owner=request.user,
                state__in=(
                    Listing.State.DRAFT,
                    Listing.State.PENDING_REVIEW,
                    Listing.State.PUBLISHED,
                    Listing.State.REJECTED,
                ),
            )
            transition_owner_listing(listing, request.user, action)
    except ValidationError as error:
        return render(
            request,
            "listings/listing_detail.html",
            {
                "listing": listing,
                "is_owner": True,
                "is_staff_viewer": False,
                "transition_error": error,
            },
            status=400,
        )
    return redirect("listing_detail", listing_id=listing.pk)
