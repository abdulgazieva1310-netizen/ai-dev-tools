from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from scheduling.forms import AvailabilityExceptionForm, AvailabilityRuleForm
from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    teacher_timezone,
)


def _require_active(request):
    if not request.user.is_active:
        raise Http404


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
