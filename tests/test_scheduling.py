"""Tests for teacher availability management (issue #20).

These run on the default test database (SQLite); no PostgreSQL-only feature is
used. The DST test derives UTC offsets from ``zoneinfo`` at the target date
instead of asserting a stored offset.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from accounts.models import User
from scheduling.forms import AvailabilityExceptionForm, AvailabilityRuleForm
from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    AvailabilityWindow,
    effective_windows,
    teacher_timezone,
    validate_iana_timezone,
)

NY = "America/New_York"
LONDON = "Europe/London"


def make_user(email="teacher@example.com", **kwargs):
    return User.objects.create_user(email, password="password", **kwargs)


@pytest.fixture
def teacher(db):
    return make_user()


@pytest.fixture
def other(db):
    return make_user("other@example.com")


def rule_data(weekday=0, start="09:00", end="10:00", timezone=NY):
    return {
        "weekday": str(weekday),
        "start_time": start,
        "end_time": end,
        "timezone": timezone,
    }


def exception_data(day, windows="", timezone=NY):
    return {"date": day.isoformat(), "timezone": timezone, "windows": windows}


def create_rule(owner, weekday=0, start="09:00", end="10:00", timezone=NY):
    return AvailabilityRule.objects.create(
        owner=owner,
        weekday=weekday,
        start_time=time.fromisoformat(start),
        end_time=time.fromisoformat(end),
        timezone=timezone,
    )


def create_exception(owner, day, windows=(), timezone=NY):
    exception = AvailabilityException.objects.create(
        owner=owner, date=day, timezone=timezone
    )
    for start, end in windows:
        AvailabilityWindow.objects.create(
            exception=exception,
            start_time=time.fromisoformat(start),
            end_time=time.fromisoformat(end),
        )
    return exception


# --- validation helpers ----------------------------------------------------


def test_iana_timezone_validation_accepts_zones_and_rejects_arbitrary_strings():
    validate_iana_timezone(NY)
    validate_iana_timezone("UTC")

    for bad in ("Mars/Phobos", "not-a-zone", "", "America/Nowhere"):
        with pytest.raises(ValidationError):
            validate_iana_timezone(bad)


# --- model behaviour -------------------------------------------------------


@pytest.mark.django_db
def test_effective_windows_follow_weekly_recurrence(teacher):
    monday = date(2026, 10, 5)
    assert monday.weekday() == 0
    create_rule(teacher, weekday=monday.weekday(), start="09:00", end="12:00")

    monday_windows = effective_windows(teacher, monday)
    tuesday_windows = effective_windows(teacher, date(2026, 10, 6))

    assert len(monday_windows) == 1
    assert monday_windows[0].start_time == time(9, 0)
    assert monday_windows[0].end_time == time(12, 0)
    assert monday_windows[0].timezone == NY
    assert tuesday_windows == []


@pytest.mark.django_db
def test_effective_windows_empty_when_nothing_matches(teacher):
    assert effective_windows(teacher, date(2026, 10, 5)) == []


@pytest.mark.django_db
def test_exception_replaces_weekly_windows_for_that_date(teacher):
    monday = date(2026, 10, 5)
    create_rule(teacher, weekday=monday.weekday(), start="09:00", end="12:00")
    create_exception(teacher, monday, windows=(("14:00", "15:00"),))

    windows = effective_windows(teacher, monday)

    assert [(w.start_time, w.end_time) for w in windows] == [(time(14, 0), time(15, 0))]
    assert windows[0].timezone == NY


@pytest.mark.django_db
def test_exception_with_no_windows_means_unavailable_all_day(teacher):
    monday = date(2026, 10, 5)
    create_rule(teacher, weekday=monday.weekday(), start="09:00", end="12:00")
    create_exception(teacher, monday)

    assert effective_windows(teacher, monday) == []


@pytest.mark.django_db
def test_exception_is_unique_per_owner_and_date(teacher):
    monday = date(2026, 10, 5)
    create_exception(teacher, monday)

    with pytest.raises(IntegrityError), transaction.atomic():
        AvailabilityException.objects.create(owner=teacher, date=monday, timezone=NY)


@pytest.mark.django_db
def test_two_teachers_do_not_share_timezone_or_overlap_scope(teacher, other):
    create_rule(teacher, weekday=0, start="09:00", end="12:00", timezone=NY)
    create_rule(other, weekday=0, start="11:00", end="13:00", timezone=LONDON)

    assert teacher_timezone(teacher) == NY
    assert teacher_timezone(other) == LONDON


# --- rule form validation --------------------------------------------------


@pytest.mark.django_db
def test_rule_form_rejects_invalid_timezone_and_saves_nothing(teacher):
    form = AvailabilityRuleForm(data=rule_data(timezone="Mars/Phobos"), owner=teacher)

    assert not form.is_valid()
    assert "timezone" in form.errors
    assert AvailabilityRule.objects.filter(owner=teacher).count() == 0


@pytest.mark.django_db
def test_rule_form_rejects_equal_and_reversed_times(teacher):
    equal = AvailabilityRuleForm(
        data=rule_data(start="09:00", end="09:00"), owner=teacher
    )
    reversed_ = AvailabilityRuleForm(
        data=rule_data(start="10:00", end="09:00"), owner=teacher
    )

    assert not equal.is_valid()
    assert "end_time" in equal.errors
    assert not reversed_.is_valid()
    assert "end_time" in reversed_.errors
    assert AvailabilityRule.objects.filter(owner=teacher).count() == 0


@pytest.mark.django_db
def test_rule_form_rejects_overlap_on_same_weekday(teacher):
    create_rule(teacher, weekday=0, start="09:00", end="12:00")

    form = AvailabilityRuleForm(
        data=rule_data(weekday=0, start="11:00", end="13:00"), owner=teacher
    )

    assert not form.is_valid()
    assert "start_time" in form.errors
    assert AvailabilityRule.objects.filter(owner=teacher).count() == 1


@pytest.mark.django_db
def test_rule_form_allows_touching_windows(teacher):
    create_rule(teacher, weekday=0, start="09:00", end="12:00")

    form = AvailabilityRuleForm(
        data=rule_data(weekday=0, start="12:00", end="14:00"), owner=teacher
    )

    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_rule_form_allows_overlap_on_a_different_weekday(teacher):
    create_rule(teacher, weekday=0, start="09:00", end="12:00")

    form = AvailabilityRuleForm(
        data=rule_data(weekday=1, start="11:00", end="13:00"), owner=teacher
    )

    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_rule_form_editing_a_rule_does_not_overlap_itself(teacher):
    rule = create_rule(teacher, weekday=0, start="09:00", end="12:00")

    form = AvailabilityRuleForm(
        data=rule_data(weekday=0, start="09:00", end="12:00"),
        instance=rule,
        owner=teacher,
    )

    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_rule_form_enforces_one_timezone_per_teacher(teacher):
    create_rule(teacher, weekday=0, timezone=NY)

    form = AvailabilityRuleForm(
        data=rule_data(weekday=1, timezone=LONDON), owner=teacher
    )

    assert not form.is_valid()
    assert "timezone" in form.errors


# --- exception form validation ---------------------------------------------


@pytest.mark.django_db
def test_exception_form_rejects_a_second_exception_for_the_same_date(teacher):
    monday = date(2026, 10, 5)
    create_exception(teacher, monday)

    form = AvailabilityExceptionForm(data=exception_data(monday), owner=teacher)

    assert not form.is_valid()
    assert "date" in form.errors
    assert AvailabilityException.objects.filter(owner=teacher).count() == 1


@pytest.mark.django_db
def test_exception_form_rejects_invalid_timezone(teacher):
    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), timezone="Nowhere/Land"),
        owner=teacher,
    )

    assert not form.is_valid()
    assert "timezone" in form.errors
    assert AvailabilityException.objects.filter(owner=teacher).count() == 0


@pytest.mark.django_db
def test_exception_form_enforces_one_timezone_per_teacher(teacher):
    create_rule(teacher, weekday=0, timezone=NY)

    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), timezone=LONDON), owner=teacher
    )

    assert not form.is_valid()
    assert "timezone" in form.errors


@pytest.mark.django_db
def test_exception_form_rejects_overlapping_windows_for_the_date(teacher):
    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), windows="09:00-12:00\n11:00-13:00"),
        owner=teacher,
    )

    assert not form.is_valid()
    assert "windows" in form.errors
    assert AvailabilityException.objects.filter(owner=teacher).count() == 0


@pytest.mark.django_db
def test_exception_form_allows_touching_windows(teacher):
    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), windows="09:00-12:00\n12:00-14:00"),
        owner=teacher,
    )

    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_exception_form_rejects_reversed_window(teacher):
    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), windows="12:00-09:00"),
        owner=teacher,
    )

    assert not form.is_valid()
    assert "windows" in form.errors


@pytest.mark.django_db
def test_exception_form_accepts_no_windows(teacher):
    form = AvailabilityExceptionForm(
        data=exception_data(date(2026, 10, 5), windows=""), owner=teacher
    )

    assert form.is_valid(), form.errors
    exception = form.save()
    assert exception.windows.count() == 0


# --- DST wall-clock stability ----------------------------------------------


@pytest.mark.django_db
def test_wall_clock_and_zone_are_preserved_across_dst_transitions(teacher):
    spring_forward = date(2026, 3, 8)
    fall_back = date(2026, 11, 1)
    assert spring_forward.weekday() == 6
    assert fall_back.weekday() == 6

    rule = create_rule(
        teacher, weekday=spring_forward.weekday(), start="09:00", end="10:00"
    )

    spring_windows = effective_windows(teacher, spring_forward)
    fall_windows = effective_windows(teacher, fall_back)

    for windows in (spring_windows, fall_windows):
        assert len(windows) == 1
        assert windows[0].start_time == time(9, 0)
        assert windows[0].end_time == time(10, 0)
        assert windows[0].timezone == NY

    zone = ZoneInfo(NY)
    spring_offset = datetime.combine(
        spring_forward, spring_windows[0].start_time, tzinfo=zone
    ).utcoffset()
    fall_offset = datetime.combine(
        fall_back, fall_windows[0].start_time, tzinfo=zone
    ).utcoffset()

    assert spring_offset == timedelta(hours=-4)
    assert fall_offset == timedelta(hours=-5)
    assert spring_offset != fall_offset

    rule.refresh_from_db()
    assert rule.start_time == time(9, 0)
    assert rule.end_time == time(10, 0)
    assert rule.timezone == NY


# --- views: ownership and CRUD ---------------------------------------------


@pytest.mark.django_db
def test_availability_requires_login(client):
    for url in (
        reverse("availability"),
        reverse("availability_rule_create"),
        reverse("availability_exception_create"),
    ):
        response = client.get(url)
        assert response.status_code == 302
        assert reverse("login") in response.url


@pytest.mark.django_db
def test_non_active_user_cannot_manage_availability(client):
    suspended = make_user("suspended@example.com", state=User.State.SUSPENDED)
    client.force_login(suspended)

    response = client.get(reverse("availability"))
    assert response.status_code == 302
    assert reverse("login") in response.url
    assert (
        client.post(reverse("availability_rule_create"), rule_data()).status_code == 302
    )
    assert AvailabilityRule.objects.filter(owner=suspended).count() == 0


@pytest.mark.django_db
def test_teacher_can_create_edit_and_delete_a_rule(client, teacher):
    client.force_login(teacher)

    response = client.post(reverse("availability_rule_create"), rule_data())
    assert response.status_code == 302
    assert response.url == reverse("availability")
    rule = AvailabilityRule.objects.get(owner=teacher)
    assert rule.owner == teacher

    response = client.post(
        reverse("availability_rule_edit", args=[rule.pk]),
        rule_data(start="08:00", end="09:00"),
    )
    assert response.status_code == 302
    rule.refresh_from_db()
    assert rule.start_time == time(8, 0)

    response = client.post(reverse("availability_rule_delete", args=[rule.pk]))
    assert response.status_code == 302
    assert not AvailabilityRule.objects.filter(pk=rule.pk).exists()


@pytest.mark.django_db
def test_teacher_can_create_edit_and_delete_an_exception(client, teacher):
    client.force_login(teacher)
    monday = date(2026, 10, 5)

    response = client.post(
        reverse("availability_exception_create"),
        exception_data(monday, windows="09:00-10:00"),
    )
    assert response.status_code == 302
    exception = AvailabilityException.objects.get(owner=teacher)
    assert list(exception.windows.values_list("start_time", "end_time")) == [
        (time(9, 0), time(10, 0))
    ]

    response = client.post(
        reverse("availability_exception_edit", args=[exception.pk]),
        exception_data(monday, windows="14:00-15:00"),
    )
    assert response.status_code == 302
    assert list(exception.windows.values_list("start_time", "end_time")) == [
        (time(14, 0), time(15, 0))
    ]

    response = client.post(
        reverse("availability_exception_delete", args=[exception.pk])
    )
    assert response.status_code == 302
    assert not AvailabilityException.objects.filter(pk=exception.pk).exists()


@pytest.mark.django_db
def test_managing_availability_does_not_require_a_profile(client, teacher):
    from profiles.models import Profile

    assert not Profile.objects.filter(user=teacher).exists()
    client.force_login(teacher)

    rule_response = client.post(reverse("availability_rule_create"), rule_data())
    exception_response = client.post(
        reverse("availability_exception_create"),
        exception_data(date(2026, 10, 5), windows="09:00-10:00"),
    )

    assert rule_response.status_code == 302
    assert exception_response.status_code == 302
    assert AvailabilityRule.objects.filter(owner=teacher).count() == 1
    assert AvailabilityException.objects.filter(owner=teacher).count() == 1


@pytest.mark.django_db
def test_non_owner_gets_404_for_rule_edit_and_delete(client, teacher, other):
    rule = create_rule(teacher, weekday=0, start="09:00", end="10:00")
    client.force_login(other)

    assert (
        client.get(reverse("availability_rule_edit", args=[rule.pk])).status_code == 404
    )
    assert (
        client.get(reverse("availability_rule_delete", args=[rule.pk])).status_code
        == 404
    )


@pytest.mark.django_db
def test_non_owner_post_cannot_modify_or_delete_a_rule(client, teacher, other):
    rule = create_rule(teacher, weekday=0, start="09:00", end="10:00")
    client.force_login(other)

    edit_response = client.post(
        reverse("availability_rule_edit", args=[rule.pk]),
        rule_data(start="08:00", end="09:00"),
    )
    delete_response = client.post(reverse("availability_rule_delete", args=[rule.pk]))

    assert edit_response.status_code == 404
    assert delete_response.status_code == 404
    rule.refresh_from_db()
    assert rule.start_time == time(9, 0)
    assert AvailabilityRule.objects.filter(pk=rule.pk).exists()


@pytest.mark.django_db
def test_non_owner_gets_404_for_exception_edit_and_delete(client, teacher, other):
    exception = create_exception(teacher, date(2026, 10, 5))
    client.force_login(other)

    assert (
        client.get(
            reverse("availability_exception_edit", args=[exception.pk])
        ).status_code
        == 404
    )
    assert (
        client.get(
            reverse("availability_exception_delete", args=[exception.pk])
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_non_owner_post_cannot_delete_another_teachers_exception(
    client, teacher, other
):
    exception = create_exception(teacher, date(2026, 10, 5))
    client.force_login(other)

    response = client.post(
        reverse("availability_exception_delete", args=[exception.pk])
    )

    assert response.status_code == 404
    assert AvailabilityException.objects.filter(pk=exception.pk).exists()


@pytest.mark.django_db
def test_invalid_rule_post_rerenders_with_errors_and_saves_nothing(client, teacher):
    client.force_login(teacher)

    response = client.post(
        reverse("availability_rule_create"), rule_data(timezone="Mars/Phobos")
    )

    assert response.status_code == 200
    assert b'role="alert"' in response.content
    assert AvailabilityRule.objects.filter(owner=teacher).count() == 0


@pytest.mark.django_db
def test_delete_removes_rule_from_effective_windows(client, teacher):
    monday = date(2026, 10, 5)
    rule = create_rule(teacher, weekday=monday.weekday(), start="09:00", end="10:00")
    assert len(effective_windows(teacher, monday)) == 1
    client.force_login(teacher)

    client.post(reverse("availability_rule_delete", args=[rule.pk]))

    assert effective_windows(teacher, monday) == []


# --- rendering and progressive enhancement ---------------------------------


@pytest.mark.django_db
def test_availability_page_groups_windows_and_shows_exceptions(client, teacher):
    monday = date(2026, 10, 5)
    create_rule(teacher, weekday=monday.weekday(), start="09:00", end="10:00")
    create_exception(teacher, monday)
    client.force_login(teacher)

    content = client.get(reverse("availability")).content.decode()

    assert "Monday" in content
    assert "09:00" in content
    assert NY in content
    assert "Unavailable all day" in content


@pytest.mark.django_db
def test_rule_form_renders_without_javascript_and_uses_partials(client, teacher):
    client.force_login(teacher)

    content = client.get(reverse("availability_rule_create")).content.decode()

    assert 'aria-label="Primary"' in content
    assert '<form method="post"' in content
    assert "csrfmiddlewaretoken" in content
    assert 'name="timezone"' in content
    assert 'name="weekday"' in content


@pytest.mark.django_db
def test_weekday_choices_cover_monday_through_sunday():
    assert [label for _, label in AvailabilityRule.Weekday.choices] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
