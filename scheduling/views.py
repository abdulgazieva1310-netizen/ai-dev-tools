from datetime import date
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from listings.models import Listing
from listings.views import listing_visible_to
from points.exceptions import InsufficientPointsError
from scheduling.forms import (
    AvailabilityExceptionForm,
    AvailabilityRuleForm,
    BookingForm,
    MeetingLinkForm,
)
from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    teacher_timezone,
)
from scheduling.services import BookingError, available_start_times, book_listing


def _require_active(request):
    if not request.user.is_active:
        raise Http404


def _parse_local_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


@login_required
@require_http_methods(["GET"])
def availability(request):
    _require_active(request)
    rules = list(AvailabilityRule.objects.filter(owner=request.user))
    weekday_groups = [
        {
            "label": label,
            "rules": [rule for rule in rules if rule.weekday == value],
        }
        for value, label in AvailabilityRule.Weekday.choices
        if any(rule.weekday == value for rule in rules)
    ]
    exceptions = AvailabilityException.objects.filter(
        owner=request.user
    ).prefetch_related("windows")
    return render(
        request,
        "scheduling/availability.html",
        {
            "weekday_groups": weekday_groups,
            "exceptions": exceptions,
            "configured_timezone": teacher_timezone(request.user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_rule_create(request):
    _require_active(request)
    form = AvailabilityRuleForm(
        request.POST if request.method == "POST" else None, owner=request.user
    )
    if request.method == "POST" and form.is_valid():
        rule = form.save(commit=False)
        rule.owner = request.user
        rule.save()
        return redirect("availability")
    return render(
        request,
        "scheduling/rule_form.html",
        {"form": form, "rule": None, "heading": "Add an availability window"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_rule_edit(request, rule_id):
    _require_active(request)
    rule = get_object_or_404(AvailabilityRule, pk=rule_id, owner=request.user)
    form = AvailabilityRuleForm(
        request.POST if request.method == "POST" else None,
        instance=rule,
        owner=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("availability")
    return render(
        request,
        "scheduling/rule_form.html",
        {"form": form, "rule": rule, "heading": "Edit an availability window"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_rule_delete(request, rule_id):
    _require_active(request)
    rule = get_object_or_404(AvailabilityRule, pk=rule_id, owner=request.user)
    if request.method == "POST":
        rule.delete()
        return redirect("availability")
    return render(
        request,
        "scheduling/confirm_delete.html",
        {"object": rule, "heading": "Delete availability window"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_exception_create(request):
    _require_active(request)
    form = AvailabilityExceptionForm(
        request.POST if request.method == "POST" else None, owner=request.user
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("availability")
    return render(
        request,
        "scheduling/exception_form.html",
        {"form": form, "exception": None, "heading": "Add a date exception"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_exception_edit(request, exception_id):
    _require_active(request)
    exception = get_object_or_404(
        AvailabilityException, pk=exception_id, owner=request.user
    )
    form = AvailabilityExceptionForm(
        request.POST if request.method == "POST" else None,
        instance=exception,
        owner=request.user,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("availability")
    return render(
        request,
        "scheduling/exception_form.html",
        {"form": form, "exception": exception, "heading": "Edit a date exception"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def availability_exception_delete(request, exception_id):
    _require_active(request)
    exception = get_object_or_404(
        AvailabilityException, pk=exception_id, owner=request.user
    )
    if request.method == "POST":
        exception.delete()
        return redirect("availability")
    return render(
        request,
        "scheduling/confirm_delete.html",
        {"object": exception, "heading": "Delete date exception"},
    )


# --- live-session booking (issue #21) --------------------------------------


def _visible_listing_or_404(listing_id, viewer):
    listing = get_object_or_404(
        Listing.objects.select_related(
            "owner", "skill", "skill__category_assignment__category"
        ),
        pk=listing_id,
    )
    if not listing_visible_to(listing, viewer):
        raise Http404
    return listing


@login_required
@require_http_methods(["GET", "POST"])
def booking_create(request, listing_id):
    _require_active(request)
    listing = _visible_listing_or_404(listing_id, request.user)

    if request.method == "POST":
        form = BookingForm(request.POST, listing=listing, learner=request.user)
        if form.is_valid():
            try:
                booking = book_listing(
                    listing=listing,
                    learner=request.user,
                    local_date=form.cleaned_data["local_date"],
                    start_time=form.cleaned_data["start_time"],
                    duration_minutes=form.cleaned_data["duration_minutes"],
                    utc_offset=form.cleaned_data["utc_offset"],
                    idempotency_key=form.cleaned_data["idempotency_key"],
                )
            except InsufficientPointsError:
                form.add_error(None, "You do not have enough points for this lesson.")
            except BookingError as error:
                form.add_error(None, str(error))
            else:
                return redirect("booking_detail", booking_id=booking.pk)
        selected_day = form.cleaned_data.get("local_date") or _parse_local_date(
            request.POST.get("local_date")
        )
    else:
        selected_day = _parse_local_date(request.GET.get("date"))
        form = BookingForm(
            listing=listing,
            learner=request.user,
            initial={"local_date": selected_day},
        )

    available_times = (
        available_start_times(listing.owner, selected_day, listing.duration_minutes)
        if selected_day and listing.listing_type == Listing.Type.LIVE
        else []
    )
    return render(
        request,
        "scheduling/booking_form.html",
        {
            "listing": listing,
            "form": form,
            "selected_day": selected_day,
            "available_times": available_times,
            "show_booking_form": request.method == "POST" or bool(available_times),
        },
    )


def _booking_or_404_for(viewer, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related("listing", "learner", "teacher", "reservation"),
        pk=booking_id,
    )
    if not viewer.is_authenticated or not viewer.is_active:
        raise Http404
    if viewer.pk not in (booking.learner_id, booking.teacher_id) and not (
        viewer.is_staff
    ):
        raise Http404
    return booking


@require_http_methods(["GET"])
def booking_detail(request, booking_id):
    booking = _booking_or_404_for(request.user, booking_id)
    zone = ZoneInfo(booking.display_timezone)
    return render(
        request,
        "scheduling/booking_detail.html",
        {
            "booking": booking,
            "start_local": booking.start_at.astimezone(zone),
            "end_local": booking.end_at.astimezone(zone),
            "is_teacher": request.user.pk == booking.teacher_id,
            "meeting_form": MeetingLinkForm(),
        },
    )


@login_required
@require_http_methods(["GET"])
def booking_list(request):
    _require_active(request)
    bookings = (
        Booking.objects.filter(Q(learner=request.user) | Q(teacher=request.user))
        .select_related("listing", "learner", "teacher")
        .order_by("-start_at", "-pk")
    )
    return render(request, "scheduling/booking_list.html", {"bookings": bookings})


@login_required
@require_POST
def booking_meeting_link(request, booking_id):
    _require_active(request)
    booking = get_object_or_404(Booking, pk=booking_id)
    if request.user.pk != booking.teacher_id:
        raise Http404
    if booking.status != Booking.Status.SCHEDULED:
        raise Http404
    form = MeetingLinkForm(request.POST)
    if form.is_valid():
        booking.meeting_url = form.cleaned_data["meeting_url"]
        booking.save(update_fields=["meeting_url"])
        return redirect("booking_detail", booking_id=booking.pk)
    zone = ZoneInfo(booking.display_timezone)
    return render(
        request,
        "scheduling/booking_detail.html",
        {
            "booking": booking,
            "start_local": booking.start_at.astimezone(zone),
            "end_local": booking.end_at.astimezone(zone),
            "is_teacher": True,
            "meeting_form": form,
        },
    )
