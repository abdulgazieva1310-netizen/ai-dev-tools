# Teacher availability

Teachers describe when learners may request live lessons as recurring weekly
windows plus date-specific exceptions. Everything lives in the `scheduling`
app. See issue #20 for the acceptance criteria; task #21 turns these local
windows into bookable UTC slots.

## Local wall-clock storage

Availability is stored as the values a clock on the wall would show:

- `AvailabilityRule.weekday` — Monday (0) through Sunday (6), matching
  `datetime.date.weekday()`.
- `AvailabilityRule.start_time` / `end_time` — `TimeField`, local wall-clock.
- `AvailabilityRule.timezone` — the IANA zone name those times are in.
- `AvailabilityException.date` — the local calendar date.
- `AvailabilityException.timezone` — the same IANA zone name.
- `AvailabilityWindow.exception` with `start_time` / `end_time` — zero or more
  wall-clock windows for an exception.

Nothing is converted to `settings.TIME_ZONE` and no fixed UTC offset or instant
is stored. A window of `09:00–10:00` in `America/New_York` stays exactly that
in the database all year; only when a concrete date is resolved does the zone
produce a UTC offset (which changes across DST).

## One timezone per teacher

A teacher has a single configured availability zone. Once any rule or
`AvailabilityException` exists, saving another record whose `timezone` differs
from `scheduling.models.teacher_timezone(owner)` is rejected with a form error.
The zone must be a name `zoneinfo.ZoneInfo` can load; arbitrary strings are
rejected server-side.

## Weekly rules, exceptions and precedence

- `AvailabilityRule` windows recur every week on their weekday.
- An `AvailabilityException` replaces **all** of the teacher's weekly windows
  for that local date. An exception with no `AvailabilityWindow` rows means the
  teacher is unavailable all day.
- There is at most one exception per owner and date, enforced by the
  `unique_availability_exception_owner_date` database constraint.
- Windows use half-open `[start, end)` semantics, so two windows that merely
  touch (`09:00–12:00` then `12:00–14:00`) are allowed while genuine overlaps
  are rejected for the same owner and weekday (rules) or exception date
  (windows). Overnight/cross-midnight windows are rejected: `end_time` must be
  strictly after `start_time`.

## Effective windows for a date

`scheduling.models.effective_windows(owner, day)` is the documented read
function:

```python
from scheduling.models import effective_windows

windows = effective_windows(teacher, date(2026, 3, 8))
for window in windows:
    window.start_time  # datetime.time, local wall-clock
    window.end_time
    window.timezone  # IANA zone in force
```

It returns the exception's windows when an exception exists for `day` (or an
empty list when the exception has no windows), otherwise the weekly rules for
`day.weekday()`, and an empty list when nothing matches. Every returned
`LocalWindow` reports the IANA zone in force.

Task #21 consumes this function to convert a selected local date and lesson
duration into a concrete UTC start/end. It must combine `day`, the window's
local `start_time`, and `window.timezone` and derive the offset with
`zoneinfo.ZoneInfo(timezone)` for that date — never assume a stored offset.
That is what keeps spring-forward and fall-back dates correct: a rule saved as
`09:00–10:00 America/New_York` resolves to `13:00–14:00 UTC` in winter and
`14:00–15:00 UTC` in summer. Task #21 also owns rejecting nonexistent DST times
and disambiguating repeated local times.

## Relationship to `USE_TZ` and `TIME_ZONE`

`config/settings.py` does not override Django's framework defaults, so
`USE_TZ = True` and `TIME_ZONE = "America/Chicago"` apply. `USE_TZ` controls
whether Django stores aware `datetime` values (such as the account
verification timestamp) in UTC. `TIME_ZONE` is the project's default display
and interpretation zone. Neither one affects teacher availability: rules and
exceptions store naive wall-clock times plus their own explicit IANA zone, so
they are independent of the project default.
