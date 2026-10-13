from django.contrib import admin

from scheduling.models import (
    AvailabilityException,
    AvailabilityRule,
    AvailabilityWindow,
)


@admin.register(AvailabilityRule)
class AvailabilityRuleAdmin(admin.ModelAdmin):
    list_display = ("owner", "weekday", "start_time", "end_time", "timezone")
    list_filter = ("weekday", "timezone")
    search_fields = ("owner__email",)


class AvailabilityWindowInline(admin.TabularInline):
    model = AvailabilityWindow
    extra = 1


@admin.register(AvailabilityException)
class AvailabilityExceptionAdmin(admin.ModelAdmin):
    list_display = ("owner", "date", "timezone")
    list_filter = ("timezone",)
    search_fields = ("owner__email",)
    inlines = [AvailabilityWindowInline]
