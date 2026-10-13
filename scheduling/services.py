"""Live-session booking and point reservation (issue #21).

Booking a live lesson and holding its point cost happen inside one
``transaction.atomic()``. Both participants are locked with a single
``select_for_update()`` statement ordered by user id, matching the lock order
used by ``points.services`` so two bookings that share a participant cannot
deadlock and two bookings with the same two users in opposite roles still take
their locks in the same order.

The point hold is created only through :mod:`points.services`; no code here
writes ``PointAccount``/``PointTransaction``/``PointReservation`` rows directly.
"""

import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import transaction

from accounts.models import User
from listings.models import Listing
from points import services as points_services
from points.models import PointTransaction
from scheduling.models import Booking, effective_windows


class BookingError(Exception):
    """A booking request that is not allowed; shown as a form error."""


class NonexistentLocalTime(BookingError):
    """The requested local wall-clock time falls in a spring-forward gap."""


class AmbiguousLocalTime(BookingError):
    """The requested local wall-clock time happens twice (fall-back)."""


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def parse_utc_offset(raw):
    """Parse ``+HH:MM``/``-HHMM`` into a ``timedelta`` (``None`` when empty)."""

    if raw is None:
        return None
    if isinstance(raw, timedelta):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    match = _OFFSET_RE.match(text)
    if match is None:
        raise ValueError("Enter a UTC offset such as -05:00.")
    hours = int(match.group(2))
    minutes = int(match.group(3))
    if hours > 23 or minutes > 59:
        raise ValueError("Enter a valid UTC offset such as -05:00.")
    sign = 1 if match.group(1) == "+" else -1
    return sign * timedelta(hours=hours, minutes=minutes)


def resolve_local_datetime(day, local_time, zone_name, utc_offset=None):
    """Resolve a local wall-clock time on ``day`` to an aware UTC datetime.

    Nonexistent (spring-forward) times are rejected. Repeated (fall-back) times
    are rejected unless ``utc_offset`` matches one of the two valid offsets for
    that instant, in which case the matching fold is chosen.
    """

    zone = ZoneInfo(zone_name)
    naive = datetime.combine(day, local_time)
    aware = naive.replace(tzinfo=zone)
    roundtrip = aware.astimezone(dt_timezone.utc).astimezone(zone).replace(tzinfo=None)
    if roundtrip != naive:
        raise NonexistentLocalTime(
            "That local time does not exist because the clock jumps forward."
        )

    offset = parse_utc_offset(utc_offset)
    offset_zero = naive.replace(tzinfo=zone, fold=0).utcoffset()
    offset_one = naive.replace(tzinfo=zone, fold=1).utcoffset()
    if offset_zero == offset_one:
        return aware.astimezone(dt_timezone.utc)
    if offset is None or offset not in (offset_zero, offset_one):
        raise AmbiguousLocalTime(
            "That local time happens twice; choose the UTC offset of the intended "
            "instant."
        )
    fold = 0 if offset == offset_zero else 1
    return naive.replace(tzinfo=zone, fold=fold).astimezone(dt_timezone.utc)


def available_start_times(teacher, day, duration_minutes):
    """Offer 15-minute start times where ``[start, start + duration)`` fits a window."""

    if not duration_minutes:
        return []
    span = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=15)
    starts = []
    for window in effective_windows(teacher, day):
        cursor = datetime.combine(day, window.start_time)
        limit = datetime.combine(day, window.end_time)
        while cursor + span <= limit:
            starts.append(cursor.time())
            cursor += step
    return sorted(set(starts))


def _window_for(teacher, day, start_time, duration_minutes):
    start = datetime.combine(day, start_time)
    end = start + timedelta(minutes=duration_minutes)
    for window in effective_windows(teacher, day):
        window_start = datetime.combine(day, window.start_time)
        window_end = datetime.combine(day, window.end_time)
        if window_start <= start and end <= window_end:
            return window
    return None


def _reserve_points(*, account, booking, teacher):
    """Create the point hold. Extracted so a test can inject a mid-way failure."""

    result = points_services.reserve(
        account,
        booking.point_cost,
        actor=booking.learner,
        source_reference=f"booking:{booking.pk}",
        bucket=PointTransaction.Bucket.BOOKING,
        recipient=teacher,
        idempotency_key=f"booking:{booking.pk}",
    )
    return result.reservation


def _replays_existing(
    existing, *, listing, learner, local_date, start_time, duration_minutes, utc_offset
):
    """Whether a repeat request with the same key carries identical parameters."""

    if existing.listing_id != listing.pk or existing.learner_id != learner.pk:
        return False
    if existing.teacher_id != listing.owner_id:
        return False
    try:
        requested_start = resolve_local_datetime(
            local_date, start_time, existing.display_timezone, utc_offset
        )
    except BookingError:
        return False
    requested_end = requested_start + timedelta(minutes=duration_minutes)
    return (
        existing.start_at == requested_start
        and existing.end_at == requested_end
        and existing.point_cost == listing.point_cost
    )


@transaction.atomic
def book_listing(
    *,
    listing,
    learner,
    local_date,
    start_time,
    duration_minutes,
    utc_offset=None,
    idempotency_key,
):
    """Create a scheduled booking and reserve its point cost, or raise BookingError.

    Locks both participants in ascending user-id order, rechecks listing and
    learner eligibility, the teacher's availability, and half-open overlaps for
    both participants before inserting anything, then reserves the points.
    """

    teacher_id = listing.owner_id
    locked = list(
        User.objects.select_for_update()
        .filter(pk__in={learner.pk, teacher_id})
        .order_by("pk")
    )
    by_pk = {user.pk: user for user in locked}
    learner = by_pk.get(learner.pk)
    teacher = by_pk.get(teacher_id)
    if learner is None or teacher is None:
        raise BookingError("The booking participants are no longer available.")

    existing = Booking.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        if _replays_existing(
            existing,
            listing=listing,
            learner=learner,
            local_date=local_date,
            start_time=start_time,
            duration_minutes=duration_minutes,
            utc_offset=utc_offset,
        ):
            return existing
        raise BookingError(
            "That booking request was already used with different details."
        )

    listing = Listing.objects.select_related("owner").get(pk=listing.pk)
    if listing.owner_id != teacher_id:
        raise BookingError("This lesson's owner changed; reload and try again.")
    if listing.listing_type != Listing.Type.LIVE:
        raise BookingError("Only live lessons can be booked.")
    if listing.state != Listing.State.PUBLISHED:
        raise BookingError("This lesson is not open for booking.")
    if not teacher.is_active:
        raise BookingError("This teacher is not accepting bookings.")
    if not learner.is_active:
        raise BookingError("Your account cannot make bookings.")
    if learner.email_verified_at is None:
        raise BookingError("Verify your email before booking a lesson.")
    if learner.pk == listing.owner_id:
        raise BookingError("You cannot book your own lesson.")
    if listing.point_cost is None or listing.point_cost < 1:
        raise BookingError("This lesson has no valid point cost.")
    if not duration_minutes or duration_minutes != listing.duration_minutes:
        raise BookingError("Choose the lesson's configured duration.")

    window = _window_for(teacher, local_date, start_time, duration_minutes)
    if window is None:
        raise BookingError("That start time is not inside the teacher's availability.")
    display_timezone = window.timezone
    start_at = resolve_local_datetime(
        local_date, start_time, display_timezone, utc_offset
    )
    end_at = start_at + timedelta(minutes=duration_minutes)

    scheduled = Booking.objects.filter(status=Booking.Status.SCHEDULED)
    if scheduled.filter(
        teacher=teacher, start_at__lt=end_at, end_at__gt=start_at
    ).exists():
        raise BookingError("That time overlaps another booking for the teacher.")
    if scheduled.filter(
        learner=learner, start_at__lt=end_at, end_at__gt=start_at
    ).exists():
        raise BookingError("That time overlaps another booking for you.")

    booking = Booking.objects.create(
        listing=listing,
        learner=learner,
        teacher=teacher,
        start_at=start_at,
        end_at=end_at,
        display_timezone=display_timezone,
        point_cost=listing.point_cost,
        status=Booking.Status.SCHEDULED,
        idempotency_key=idempotency_key,
    )
    account = points_services.ensure_account(learner)
    booking.reservation = _reserve_points(
        account=account, booking=booking, teacher=teacher
    )
    booking.save(update_fields=["reservation"])
    return booking
