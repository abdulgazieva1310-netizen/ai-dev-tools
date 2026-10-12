from django.contrib import admin
from django.core.exceptions import PermissionDenied

from listings.forms import CategoryAdminForm, ListingModerationForm
from listings.models import Category, Listing, SkillCategory
from listings.workflow import transition_staff_listing


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    form = CategoryAdminForm
    list_display = ("name", "normalized_name")
    search_fields = ("name", "normalized_name")
    ordering = ("name",)


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ("skill", "category")
    list_filter = ("category",)
    search_fields = ("skill__name", "category__name")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    form = ListingModerationForm
    list_display = ("title", "owner", "skill", "state", "updated_at")
    list_filter = ("state", "skill__category_assignment__category", "level")
    search_fields = ("title", "description", "owner__email", "skill__name")
    ordering = ("-updated_at",)
    readonly_fields = (
        "owner",
        "skill",
        "listing_type",
        "title",
        "description",
        "learning_outcomes",
        "level",
        "duration_minutes",
        "created_at",
        "updated_at",
    )
    fields = (
        "owner",
        "skill",
        "listing_type",
        "title",
        "description",
        "learning_outcomes",
        "level",
        "duration_minutes",
        "state",
        "rejection_reason",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            original = Listing.objects.get(pk=obj.pk)
            if not request.user.is_active or not request.user.is_staff:
                raise PermissionDenied("Active staff access is required.")
            transition_staff_listing(original, obj.state, obj.rejection_reason or "")
            obj.state = original.state
            obj.rejection_reason = original.rejection_reason
        else:
            super().save_model(request, obj, form, change)
