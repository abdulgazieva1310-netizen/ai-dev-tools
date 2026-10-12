"""Read-only Django admin for the point ledger.

Operators may inspect accounts and ledger entries, but the admin never creates,
edits or deletes them: balances change only through ``points.services`` and the
ledger is append-only.
"""

from django.contrib import admin

from points.models import PointAccount, PointTransaction


@admin.register(PointAccount)
class PointAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "available", "reserved", "updated_at")
    search_fields = ("user__email",)
    ordering = ("user_id",)
    readonly_fields = ("user", "available", "reserved", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "account",
        "amount",
        "bucket",
        "type",
        "actor",
        "created_at",
    )
    list_filter = ("bucket", "type")
    search_fields = ("account__user__email", "source_reference")
    ordering = ("-created_at", "-id")
    readonly_fields = (
        "account",
        "amount",
        "bucket",
        "type",
        "actor",
        "source_reference",
        "idempotency_key",
        "arguments_digest",
        "reason",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
