"""Tests for live-session booking and point reservation (issue #21).

Eligibility, availability, half-open overlap, DST wall-clock resolution,
idempotency, meeting-link privacy and participant scoping behave the same on
any backend, so those tests run everywhere. Row locking, concurrent slot
claims and whole-transaction rollback only behave like production on
PostgreSQL, so those tests use ``require_postgres()``: when this file is run
explicitly against SQLite they fail loudly instead of passing for the wrong
reason, and the implicit whole-suite SQLite run skips them.
"""

import os
import pathlib
import re
import sys
import threading
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from listings.models import Listing
from points import services as points_services
from points.exceptions import InsufficientPointsError
from points.models import PointReservation, PointTransaction
from profiles.models import Profile
from scheduling.forms import BookingForm
from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    AvailabilityWindow,
    Booking,
)
from scheduling.services import (
    AmbiguousLocalTime,
    BookingError,
    NonexistentLocalTime,
    available_start_times,
    book_listing,
    resolve_local_datetime,
)

NY = "America/New_York"
MONDAY = date(2026, 10, 5)  # weekday 0
SPRING_FORWARD = date(2026, 3, 8)  # Sunday, 02:00 -> 03:00 America/New_York
FALL_BACK = date(2026, 11, 1)  # Sunday, 02:00 -> 01:00 America/New_York
UTC = dt_timezone.utc


def require_postgres():
    """Guard for PostgreSQL-only assertions."""
    if connection.vendor == "postgresql":
        return
    if os.environ.get("RUN_POSTGRES_BOOKING_TESTS") == "1" or any(
        argument.endswith("tests/test_booking.py") for argument in sys.argv
    ):
        pytest.fail(
            "Booking locking/concurrency needs the Compose PostgreSQL database; "
            f"the configured backend is {connection.vendor}."
        )
    pytest.skip("PostgreSQL-only booking tests run in Docker Compose.")


# --- helpers ------------------------------------------------------------------


def make_user(email, *, verified=True, **kwargs):
    if verified and "email_verified_at" not in kwargs:
        kwargs["email_verified_at"] = timezone.now()
    return User.objects.create_user(email, password="password", **kwargs)


def make_teacher(email="teacher@example.com", **kwargs):
    user = make_user(email, **kwargs)
    Profile.objects.create(
        user=user, display_name=email, visibility=Profile.Visibility.PUBLIC
    )
    return user


def make_listing(
    owner,
    *,
    state=Listing.State.PUBLISHED,
    listing_type=Listing.Type.LIVE,
    duration=60,
    cost=10,
    title="Lesson",
):
    return Listing.objects.create(
        owner=owner,
        listing_type=listing_type,
        state=state,
        title=title,
        duration_minutes=duration,
        point_cost=cost,
    )


def add_rule(owner, *, weekday=0, start=time(9, 0), end=time(12, 0), tz=NY):
    return AvailabilityRule.objects.create(
        owner=owner,
        weekday=weekday,
        start_time=start,
        end_time=end,
        timezone=tz,
    )


def add_exception(owner, day, *, windows=((time(0, 0), time(6, 0)),), tz=NY):
    exception = AvailabilityException.objects.create(owner=owner, date=day, timezone=tz)
    for start, end in windows:
        AvailabilityWindow.objects.create(
            exception=exception, start_time=start, end_time=end
        )
    return exception


def fund(user, amount, *, key="fund"):
    account = points_services.ensure_account(user)
    points_services.issue_points(
        account,
        amount,
        actor=None,
        source_reference=key,
        bucket=PointTransaction.Bucket.GENERAL,
        idempotency_key=key,
    )
    return account


def book(
    listing,
    learner,
    *,
    day=MONDAY,
    start=time(9, 0),
    duration=60,
    key="key-1",
    utc_offset=None,
):
    return book_listing(
        listing=listing,
        learner=learner,
        local_date=day,
        start_time=start,
        duration_minutes=duration,
        utc_offset=utc_offset,
        idempotency_key=key,
    )


def run_threads(worker, count, *, timeout=30):
    barrier = threading.Barrier(count)
    errors = []

    def runner(index):
        connection.close()
        try:
            barrier.wait(timeout=10)
            worker(index)
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    return errors


# --- fixtures -----------------------------------------------------------------


@pytest.fixture
def teacher(db):
    return make_teacher()


@pytest.fixture
def learner(db):
    return make_user("learner@example.com")


@pytest.fixture
def staff(db):
    return make_user("staff@example.com", is_staff=True)


@pytest.fixture
def listing(teacher):
    return make_listing(teacher)


@pytest.fixture
def monday_window(teacher):
    return add_rule(teacher, weekday=MONDAY.weekday())


# --- model shape and point_cost validation ------------------------------------


def test_booking_status_defines_scheduled_and_reserved_outcomes():
    assert Booking.Status.SCHEDULED == "scheduled"
    assert set(Booking.Status.values) == {
        "scheduled",
        "completed",
        "disputed",
        "cancelled",
        "no_show_learner",
        "no_show_teacher",
    }


def test_booking_relation_fields_are_protected():
    assert Booking._meta.get_field("listing").remote_field.on_delete is models.PROTECT
    assert Booking._meta.get_field("learner").remote_field.on_delete is models.PROTECT
    assert Booking._meta.get_field("teacher").remote_field.on_delete is models.PROTECT
    reservation = Booking._meta.get_field("reservation")
    assert reservation.remote_field.on_delete is models.PROTECT
    assert reservation.one_to_one
    assert Booking._meta.get_field("idempotency_key").unique


@pytest.mark.django_db
def test_published_live_listing_rejects_missing_or_nonpositive_point_cost(teacher):
    for bad in (None, 0):
        listing = Listing(
            owner=teacher,
            listing_type=Listing.Type.LIVE,
            state=Listing.State.PUBLISHED,
            title="x",
            duration_minutes=60,
            point_cost=bad,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            listing.save()


@pytest.mark.django_db
def test_submit_validation_flags_a_nonpositive_point_cost(teacher):
    listing = Listing(
        owner=teacher,
        listing_type=Listing.Type.LIVE,
        title="T",
        description="D",
        learning_outcomes="O",
        level=Listing.Level.BEGINNER,
        duration_minutes=60,
        point_cost=0,
    )
    with pytest.raises(ValidationError) as excinfo:
        listing.validate_complete()
    assert "point_cost" in excinfo.value.error_dict


# --- availability to bookable start times -------------------------------------


@pytest.mark.django_db
def test_available_start_times_step_15_minutes_inside_a_window(teacher, monday_window):
    starts = available_start_times(teacher, MONDAY, 60)
    assert starts == [
        time(9, 0),
        time(9, 15),
        time(9, 30),
        time(9, 45),
        time(10, 0),
        time(10, 15),
        time(10, 30),
        time(10, 45),
        time(11, 0),
    ]
    assert time(11, 15) not in starts


@pytest.mark.django_db
def test_available_start_times_empty_without_windows(teacher):
    assert available_start_times(teacher, MONDAY, 60) == []


@pytest.mark.django_db
def test_available_start_times_empty_for_exception_with_no_windows(teacher):
    add_exception(teacher, MONDAY, windows=())
    assert available_start_times(teacher, MONDAY, 60) == []


# --- DST wall-clock resolution -------------------------------------------------


def test_resolved_utc_offsets_shift_across_a_dst_boundary():
    spring_local = datetime(2026, 3, 8, 9, 0, tzinfo=ZoneInfo(NY))
    autumn_local = datetime(2026, 11, 1, 9, 0, tzinfo=ZoneInfo(NY))
    assert spring_local.utcoffset() == timedelta(hours=-4)
    assert autumn_local.utcoffset() == timedelta(hours=-5)
    assert spring_local.utcoffset() != autumn_local.utcoffset()

    spring = resolve_local_datetime(SPRING_FORWARD, time(9, 0), NY)
    autumn = resolve_local_datetime(FALL_BACK, time(9, 0), NY)
    assert spring == datetime(2026, 3, 8, 13, 0, tzinfo=UTC)
    assert autumn == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def test_nonexistent_spring_forward_local_time_is_rejected():
    with pytest.raises(NonexistentLocalTime):
        resolve_local_datetime(SPRING_FORWARD, time(2, 30), NY)


def test_ambiguous_fall_back_time_needs_a_matching_utc_offset():
    with pytest.raises(AmbiguousLocalTime):
        resolve_local_datetime(FALL_BACK, time(1, 30), NY)
    with pytest.raises(AmbiguousLocalTime):
        resolve_local_datetime(FALL_BACK, time(1, 30), NY, "-03:00")

    first = resolve_local_datetime(FALL_BACK, time(1, 30), NY, "-04:00")
    second = resolve_local_datetime(FALL_BACK, time(1, 30), NY, "-05:00")
    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert second == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert first != second


@pytest.mark.django_db
def test_booking_rejects_nonexistent_local_time(teacher, learner):
    add_exception(teacher, SPRING_FORWARD)
    listing = make_listing(teacher)
    fund(learner, 50)

    with pytest.raises(NonexistentLocalTime):
        book(listing, learner, day=SPRING_FORWARD, start=time(2, 30))

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_booking_resolves_an_ambiguous_time_with_an_explicit_offset(teacher, learner):
    add_exception(teacher, FALL_BACK)
    listing = make_listing(teacher)
    fund(learner, 50)

    booking = book(
        listing, learner, day=FALL_BACK, start=time(1, 30), utc_offset="-05:00"
    )

    assert booking.start_at == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


# --- service eligibility -------------------------------------------------------


@pytest.mark.django_db
def test_valid_booking_creates_booking_and_hold(listing, monday_window, learner):
    account = fund(learner, 50)

    booking = book(listing, learner)

    assert booking.status == Booking.Status.SCHEDULED
    assert booking.learner_id == learner.pk
    assert booking.teacher_id == listing.owner_id
    assert booking.display_timezone == NY
    assert booking.point_cost == listing.point_cost
    assert booking.start_at == datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
    assert booking.end_at == datetime(2026, 10, 5, 14, 0, tzinfo=UTC)
    assert booking.reservation is not None
    assert booking.reservation.ledger_key == f"booking:{booking.pk}"
    assert booking.reservation.source_reference == f"booking:{booking.pk}"
    account.refresh_from_db()
    assert (account.available, account.reserved) == (40, 10)
    assert (
        PointTransaction.objects.filter(idempotency_key=f"booking:{booking.pk}").count()
        == 1
    )


@pytest.mark.django_db
def test_self_booking_is_rejected(listing, monday_window, teacher):
    fund(teacher, 50)

    with pytest.raises(BookingError):
        book(listing, teacher)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_non_published_listing_is_rejected(teacher, learner, monday_window):
    draft = make_listing(teacher, state=Listing.State.DRAFT)
    fund(learner, 50)

    with pytest.raises(BookingError):
        book(draft, learner)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_non_live_listing_is_rejected(teacher, learner, monday_window):
    transcript = make_listing(teacher, listing_type=Listing.Type.TRANSCRIPT)
    fund(learner, 50)

    with pytest.raises(BookingError):
        book(transcript, learner)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_unverified_learner_is_rejected(listing, monday_window):
    unverified = make_user("unverified@example.com", verified=False)
    fund(unverified, 50)

    with pytest.raises(BookingError):
        book(listing, unverified)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_inactive_learner_is_rejected(listing, monday_window):
    suspended = make_user("suspended@example.com", state=User.State.SUSPENDED)
    fund(suspended, 50)

    with pytest.raises(BookingError):
        book(listing, suspended)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_inactive_teacher_is_rejected(teacher, learner, monday_window):
    teacher.state = User.State.SUSPENDED
    teacher.save(update_fields=["state"])
    listing = make_listing(teacher)
    fund(learner, 50)

    with pytest.raises(BookingError):
        book(listing, learner)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_outside_availability_is_rejected(listing, monday_window, learner):
    fund(learner, 50)

    with pytest.raises(BookingError):
        book(listing, learner, start=time(13, 0))

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_duration_mismatch_is_rejected(listing, monday_window, learner):
    fund(learner, 50)

    with pytest.raises(BookingError):
        book(listing, learner, duration=30)

    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_teacher_conflict_is_rejected(listing, monday_window, learner):
    other = make_user("learner2@example.com")
    fund(learner, 50)
    fund(other, 50)
    book(listing, learner, start=time(9, 0), key="first")

    with pytest.raises(BookingError):
        book(listing, other, start=time(9, 30), key="second")

    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1


@pytest.mark.django_db
def test_learner_conflict_is_rejected(teacher, learner):
    add_rule(teacher, weekday=MONDAY.weekday())
    teacher2 = make_teacher("teacher2@example.com")
    add_rule(teacher2, weekday=MONDAY.weekday())
    listing = make_listing(teacher)
    listing2 = make_listing(teacher2, title="Lesson 2")
    fund(learner, 100)

    book(listing, learner, start=time(9, 0), key="first")

    with pytest.raises(BookingError):
        book(listing2, learner, start=time(9, 30), key="second")

    assert Booking.objects.count() == 1


@pytest.mark.django_db
def test_half_open_back_to_back_bookings_are_allowed(listing, monday_window, learner):
    fund(learner, 100)

    first = book(listing, learner, start=time(9, 0), key="first")
    second = book(listing, learner, start=time(10, 0), key="second")

    assert first.end_at == second.start_at
    assert Booking.objects.count() == 2


@pytest.mark.django_db
def test_insufficient_points_rejects_and_leaves_balances_unchanged(
    listing, monday_window, learner
):
    account = fund(learner, 5)

    with pytest.raises(InsufficientPointsError):
        book(listing, learner)

    account.refresh_from_db()
    assert (account.available, account.reserved) == (5, 0)
    assert Booking.objects.count() == 0
    assert PointReservation.objects.count() == 0
    assert (
        PointTransaction.objects.filter(type=PointTransaction.Type.RESERVE).count() == 0
    )


# --- idempotency ---------------------------------------------------------------


@pytest.mark.django_db
def test_repeat_booking_with_the_same_key_replays_the_booking(
    listing, monday_window, learner
):
    account = fund(learner, 50)

    first = book(listing, learner, key="same")
    second = book(listing, learner, key="same")

    assert first.pk == second.pk
    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1
    account.refresh_from_db()
    assert (account.available, account.reserved) == (40, 10)


@pytest.mark.django_db
def test_same_key_with_different_parameters_is_a_conflict(
    listing, monday_window, learner
):
    fund(learner, 50)
    book(listing, learner, start=time(9, 0), key="dup")

    with pytest.raises(BookingError):
        book(listing, learner, start=time(9, 15), key="dup")

    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1


# --- atomicity and locking (PostgreSQL only) -----------------------------------


@pytest.mark.django_db(transaction=True)
def test_injected_failure_between_booking_and_reservation_rolls_back(
    listing, monday_window, learner
):
    require_postgres()
    account = fund(learner, 50)
    bookings_before = Booking.objects.count()
    transactions_before = PointTransaction.objects.count()

    with patch("scheduling.services._reserve_points", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            book(listing, learner)

    assert Booking.objects.count() == bookings_before
    assert PointReservation.objects.count() == 0
    assert PointTransaction.objects.count() == transactions_before
    account.refresh_from_db()
    assert (account.available, account.reserved) == (50, 0)


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_creates_one_booking_and_one_reservation(
    listing, monday_window, learner
):
    require_postgres()
    account = fund(learner, 50)
    results = [None] * 5

    def worker(index):
        results[index] = book_listing(
            listing=Listing.objects.get(pk=listing.pk),
            learner=User.objects.get(pk=learner.pk),
            local_date=MONDAY,
            start_time=time(9, 0),
            duration_minutes=60,
            utc_offset=None,
            idempotency_key="race-key",
        )

    errors = run_threads(worker, 5)
    assert not errors, errors
    assert {result.pk for result in results} == {results[0].pk}
    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1
    account.refresh_from_db()
    assert (account.available, account.reserved) == (40, 10)


@pytest.mark.django_db(transaction=True)
def test_two_learners_racing_one_slot_produce_exactly_one_booking(
    listing, monday_window
):
    require_postgres()
    learner_a = make_user("racer-a@example.com")
    learner_b = make_user("racer-b@example.com")
    fund(learner_a, 50, key="fund-a")
    fund(learner_b, 50, key="fund-b")
    successes = []
    rejections = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker(user_pk):
        connection.close()
        try:
            barrier.wait(timeout=10)
            booking = book_listing(
                listing=Listing.objects.get(pk=listing.pk),
                learner=User.objects.get(pk=user_pk),
                local_date=MONDAY,
                start_time=time(9, 0),
                duration_minutes=60,
                utc_offset=None,
                idempotency_key=f"race-{user_pk}",
            )
            with lock:
                successes.append(booking)
        except BookingError as error:
            with lock:
                rejections.append(error)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=worker, args=(learner_a.pk,)),
        threading.Thread(target=worker, args=(learner_b.pk,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(successes) == 1, (successes, rejections)
    assert len(rejections) == 1
    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1
    for racer in (learner_a, learner_b):
        account = points_services.ensure_account(racer)
        account.refresh_from_db()
        assert account.reserved in (0, 10)
    reserved_total = sum(
        points_services.ensure_account(racer).reserved
        for racer in (learner_a, learner_b)
    )
    assert reserved_total == 10


@pytest.mark.django_db(transaction=True)
def test_opposite_role_pairs_do_not_deadlock():
    require_postgres()
    first = make_teacher("pair-a@example.com")
    second = make_teacher("pair-b@example.com")
    add_rule(first, weekday=MONDAY.weekday())
    add_rule(second, weekday=MONDAY.weekday())
    listing_first = make_listing(first, title="A teaches")
    listing_second = make_listing(second, title="B teaches")
    fund(first, 100, key="fund-a")
    fund(second, 100, key="fund-b")
    barrier = threading.Barrier(2)
    errors = []

    def worker(learner_pk, listing_pk, start):
        connection.close()
        try:
            barrier.wait(timeout=10)
            book_listing(
                listing=Listing.objects.get(pk=listing_pk),
                learner=User.objects.get(pk=learner_pk),
                local_date=MONDAY,
                start_time=start,
                duration_minutes=60,
                utc_offset=None,
                idempotency_key=f"pair-{learner_pk}",
            )
        except Exception as error:  # pragma: no cover - surfaced by the assert
            errors.append(error)
        finally:
            connection.close()

    threads = [
        threading.Thread(target=worker, args=(first.pk, listing_second.pk, time(9, 0))),
        threading.Thread(
            target=worker, args=(second.pk, listing_first.pk, time(10, 0))
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert Booking.objects.count() == 2


# --- views: booking page and form ---------------------------------------------


@pytest.mark.django_db
def test_booking_page_offers_only_available_start_times(
    client, listing, monday_window, learner
):
    client.force_login(learner)

    response = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert 'value="09:00"' in content
    assert 'value="11:00"' in content
    assert 'value="11:15"' not in content
    assert 'value="13:00"' not in content


@pytest.mark.django_db
def test_booking_page_with_empty_windows_offers_no_start_times(
    client, listing, learner
):
    client.force_login(learner)

    response = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "No available start times" in content
    assert 'name="start_time"' not in content


@pytest.mark.django_db
def test_booking_page_is_404_for_an_invisible_listing(client, teacher, learner):
    draft = make_listing(teacher, state=Listing.State.DRAFT)
    client.force_login(learner)

    response = client.get(reverse("booking_create", args=[draft.pk]))

    assert response.status_code == 404


def extract_idempotency_key(content):
    match = re.search(r'name="idempotency_key"[^>]*value="([^"]+)"', content)
    assert match, content
    return match.group(1)


@pytest.mark.django_db
def test_valid_post_creates_booking_and_repeat_post_replays_it(
    client, listing, monday_window, learner
):
    fund(learner, 50)
    client.force_login(learner)
    page = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )
    key = extract_idempotency_key(page.content.decode())
    data = {
        "idempotency_key": key,
        "local_date": MONDAY.isoformat(),
        "start_time": "09:00",
        "duration_minutes": "60",
        "utc_offset": "",
    }

    first = client.post(reverse("booking_create", args=[listing.pk]), data)
    booking = Booking.objects.get()
    assert first.status_code == 302
    assert first.url == reverse("booking_detail", args=[booking.pk])

    second = client.post(reverse("booking_create", args=[listing.pk]), data)
    assert second.status_code == 302
    assert second.url == reverse("booking_detail", args=[booking.pk])
    assert Booking.objects.count() == 1
    assert PointReservation.objects.count() == 1


@pytest.mark.django_db
def test_post_with_mismatched_duration_is_rejected(
    client, listing, monday_window, learner
):
    fund(learner, 50)
    client.force_login(learner)
    page = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )
    key = extract_idempotency_key(page.content.decode())

    response = client.post(
        reverse("booking_create", args=[listing.pk]),
        {
            "idempotency_key": key,
            "local_date": MONDAY.isoformat(),
            "start_time": "09:00",
            "duration_minutes": "30",
            "utc_offset": "",
        },
    )

    assert response.status_code == 200
    assert b'role="alert"' in response.content
    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_post_with_a_missing_duration_is_rejected(
    client, listing, monday_window, learner
):
    fund(learner, 50)
    client.force_login(learner)
    page = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )
    key = extract_idempotency_key(page.content.decode())

    response = client.post(
        reverse("booking_create", args=[listing.pk]),
        {
            "idempotency_key": key,
            "local_date": MONDAY.isoformat(),
            "start_time": "09:00",
            "utc_offset": "",
        },
    )

    assert response.status_code == 200
    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_post_with_a_slot_outside_availability_is_rejected(
    client, listing, monday_window, learner
):
    fund(learner, 50)
    client.force_login(learner)
    page = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )
    key = extract_idempotency_key(page.content.decode())

    response = client.post(
        reverse("booking_create", args=[listing.pk]),
        {
            "idempotency_key": key,
            "local_date": MONDAY.isoformat(),
            "start_time": "13:00",
            "duration_minutes": "60",
            "utc_offset": "",
        },
    )

    assert response.status_code == 200
    assert Booking.objects.count() == 0


@pytest.mark.django_db
def test_self_booking_post_is_rejected_with_a_form_error(
    client, listing, monday_window, teacher
):
    fund(teacher, 50)
    client.force_login(teacher)
    page = client.get(
        reverse("booking_create", args=[listing.pk]), {"date": MONDAY.isoformat()}
    )
    key = extract_idempotency_key(page.content.decode())

    response = client.post(
        reverse("booking_create", args=[listing.pk]),
        {
            "idempotency_key": key,
            "local_date": MONDAY.isoformat(),
            "start_time": "09:00",
            "duration_minutes": "60",
            "utc_offset": "",
        },
    )

    assert response.status_code == 200
    assert b'role="alert"' in response.content
    assert Booking.objects.count() == 0


# --- views: participant scoping ------------------------------------------------


@pytest.mark.django_db
def test_booking_detail_is_scoped_to_participants_and_staff(
    client, listing, monday_window, learner, staff, teacher
):
    fund(learner, 50)
    booking = book(listing, learner)
    url = reverse("booking_detail", args=[booking.pk])

    client.force_login(learner)
    assert client.get(url).status_code == 200

    client.force_login(teacher)
    assert client.get(url).status_code == 200

    client.force_login(staff)
    assert client.get(url).status_code == 200

    outsider = make_user("outsider@example.com")
    client.force_login(outsider)
    assert client.get(url).status_code == 404

    client.logout()
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_booking_detail_renders_local_time_timezone_and_status(
    client, listing, monday_window, learner
):
    fund(learner, 50)
    booking = book(listing, learner)
    client.force_login(learner)

    content = client.get(reverse("booking_detail", args=[booking.pk])).content.decode()

    assert "09:00" in content
    assert "10:00" in content
    assert NY in content
    assert "Scheduled" in content


@pytest.mark.django_db
def test_my_bookings_lists_only_my_own_bookings(
    client, listing, monday_window, learner, teacher
):
    fund(learner, 50)
    book(listing, learner, key="booking-1")
    url = reverse("booking_list")

    client.force_login(learner)
    learner_content = client.get(url).content.decode()
    assert listing.title in learner_content

    client.force_login(teacher)
    teacher_content = client.get(url).content.decode()
    assert listing.title in teacher_content

    outsider = make_user("outsider2@example.com")
    client.force_login(outsider)
    outsider_content = client.get(url).content.decode()
    assert listing.title not in outsider_content


# --- meeting link privacy and authorization ------------------------------------


@pytest.mark.django_db
def test_only_the_teacher_participant_can_set_the_meeting_link(
    client, listing, monday_window, learner, teacher, staff
):
    fund(learner, 50)
    booking = book(listing, learner)
    url = reverse("booking_meeting_link", args=[booking.pk])

    client.force_login(teacher)
    response = client.post(url, {"meeting_url": "https://meet.example.com/room"})
    assert response.status_code == 302
    booking.refresh_from_db()
    assert booking.meeting_url == "https://meet.example.com/room"

    client.force_login(learner)
    assert (
        client.post(url, {"meeting_url": "https://evil.example.com"}).status_code == 404
    )

    client.force_login(staff)
    assert (
        client.post(url, {"meeting_url": "https://evil.example.com"}).status_code == 404
    )

    outsider = make_user("outsider3@example.com")
    client.force_login(outsider)
    assert (
        client.post(url, {"meeting_url": "https://evil.example.com"}).status_code == 404
    )

    booking.refresh_from_db()
    assert booking.meeting_url == "https://meet.example.com/room"


@pytest.mark.django_db
def test_meeting_link_is_shown_only_to_authorized_detail_viewers(
    client, listing, monday_window, learner, teacher
):
    fund(learner, 50)
    booking = book(listing, learner)
    booking.meeting_url = "https://meet.example.com/secret-room"
    booking.save(update_fields=["meeting_url"])
    url = reverse("booking_detail", args=[booking.pk])

    client.force_login(learner)
    assert "secret-room" in client.get(url).content.decode()

    client.force_login(teacher)
    assert "secret-room" in client.get(url).content.decode()

    outsider = make_user("outsider4@example.com")
    client.force_login(outsider)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_meeting_url_never_appears_in_listing_responses(
    client, listing, monday_window, learner, teacher
):
    fund(learner, 50)
    booking = book(listing, learner)
    booking.meeting_url = "https://secret.example.com/live-room"
    booking.save(update_fields=["meeting_url"])
    client.force_login(learner)

    for url in (
        reverse("listing_detail", args=[listing.pk]),
        reverse("listing_index"),
        reverse("listing_search"),
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert b"secret.example.com" not in response.content


# --- no direct points writes ---------------------------------------------------


def test_scheduling_services_only_write_points_through_the_service():
    source = pathlib.Path("scheduling/services.py").read_text()
    assert "PointAccount.objects" not in source
    assert "PointReservation.objects" not in source
    assert "PointTransaction.objects" not in source
    assert "points_services.reserve(" in source


@pytest.mark.django_db
def test_booking_form_generates_a_distinct_hidden_key_per_render(listing, learner):
    first = BookingForm(listing=listing, learner=learner)
    second = BookingForm(listing=listing, learner=learner)

    assert first.initial["idempotency_key"]
    assert first.initial["idempotency_key"] != second.initial["idempotency_key"]
