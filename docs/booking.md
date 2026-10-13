# Live-session booking and point reservation

A verified learner can book a published live lesson at a slot inside the
teacher's availability. Creating the `scheduling.Booking` and holding the
listing's point cost happen in one atomic, idempotent, deadlock-safe
transaction, so retries and concurrent claims cannot double-book either
participant or double-reserve points. See issue #21 for the acceptance
criteria; task #20 provides the availability windows and tasks #22/#23 later
capture or release the hold through `Booking.reservation`.

## Eligibility

`scheduling.services.book_listing(...)` rejects a request unless every one of
these holds:

- the listing's `listing_type` is `live` and its `state` is `published`;
- the listing owner (the teacher) is active;
- the learner is authenticated, `is_active`, and has a non-null
  `email_verified_at`;
- the learner is not the listing owner.

The booking view additionally 404s a listing the viewer may not see, using the
same `listings.views.listing_visible_to` rule as the rest of the site. Every
rejection writes no `Booking`, no `PointReservation` and no ledger entry.

## Bookable start times

For a selected local date the booking page offers 15-minute start times where
`[start, start + listing.duration_minutes)` fits entirely inside one
`scheduling.models.effective_windows(teacher, day)` window. A date whose
`effective_windows` is empty offers no times. Submitting re-derives the windows
and rejects a slot that does not fit, a `duration_minutes` that is missing or
differs from the listing, and a duration outside the 15-to-180-minute range.

## Timezone and DST

Windows are local wall-clock values plus an IANA zone, so the request date is
resolved with `zoneinfo.ZoneInfo(display_timezone)`:

- a nonexistent spring-forward local time is rejected;
- a repeated fall-back local time is rejected unless the request carries an
  explicit UTC offset (`utc_offset`, for example `-05:00`) that matches one of
  the two valid offsets for that instant, which selects the correct fold.

The resolved instant is stored on `Booking.start_at`/`end_at` as aware UTC, and
the zone used is stored as `display_timezone` so the detail view can render the
original wall-clock time.

## Atomic transaction and locking

`book_listing` runs inside one `transaction.atomic()` and, in order:

1. locks both participants with a single
   `User.objects.select_for_update().filter(pk__in=[learner.pk, teacher.pk]).order_by("pk")`
   (ascending user id, matching the `user_id` lock order used by
   `points.services`, so two bookings that share a participant or an
   opposite-role pair cannot deadlock);
2. rechecks listing and learner eligibility;
3. rechecks the teacher's availability window for the date and duration;
4. rechecks half-open `[start, end)` overlaps against every other `scheduled`
   booking for the teacher and, separately, for the learner;
5. creates the `Booking` with `status="scheduled"`;
6. calls `points.services.reserve(...)` and stores the returned
   `PointReservation` on `Booking.reservation`.

Any failure — eligibility, availability, overlap, or points, including
`points.exceptions.InsufficientPointsError` — aborts the whole transaction and
leaves no booking, reservation or ledger entry. Only `points.services` writes
point rows; this app imports `PointTransaction` solely for the
`PointTransaction.Bucket.BOOKING` constant.

The hold is created with:

```python
points.services.reserve(
    learner_account,
    listing.point_cost,
    actor=learner,
    source_reference=f"booking:{booking.pk}",
    bucket=PointTransaction.Bucket.BOOKING,
    recipient=teacher,
    idempotency_key=f"booking:{booking.pk}",
)
```

Tasks #22/#23 find the hold through `booking.reservation`, whose
`ledger_key`/`source_reference` is `booking:{booking.pk}`.

## Idempotency

The confirmation form carries a server-generated `idempotency_key` stored in
the unique `Booking.idempotency_key`. A repeat POST with the same key and the
same parameters returns the existing booking and writes no second booking or
reservation. The same key with different parameters is rejected as a conflict.

## Pages

All pages are server-rendered and work without JavaScript.

- `GET/POST /listings/<id>/book/` (`booking_create`) — choose a date, then a
  start time, and book.
- `GET /bookings/` (`booking_list`) — the participant's own bookings.
- `GET /bookings/<id>/` (`booking_detail`) — `start_at`/`end_at` rendered in
  `display_timezone` plus the current status. Only the learner, the teacher, or
  an active staff user may view it; everyone else (including anonymous) gets a
  404.
- `POST /bookings/<id>/meeting-link/` (`booking_meeting_link`) — only the
  teacher of a `scheduled` booking may set or replace `meeting_url`.

The optional `meeting_url` is shown only in the booking detail to authorized
viewers and never appears in listing index, search or detail responses.
