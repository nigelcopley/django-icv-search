"""Admin registrations for icv-search models."""

from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from icv_search.models import IndexSyncLog, SearchIndex, SearchQueryAggregate, SearchQueryLog
from icv_search.models.click_tracking import SearchClick, SearchClickAggregate
from icv_search.models.merchandising import (
    BoostRule,
    QueryRedirect,
    QueryRewrite,
    SearchBanner,
    SearchPin,
    ZeroResultFallback,
)


@admin.register(SearchIndex)
class SearchIndexAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "tenant_id",
        "engine_uid",
        "document_count",
        "is_synced",
        "is_active",
        "last_synced_at",
    ]
    list_filter = ["is_synced", "is_active"]
    search_fields = ["name", "tenant_id", "engine_uid"]
    readonly_fields = [
        "engine_uid",
        "document_count",
        "is_synced",
        "last_synced_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (None, {"fields": ["name", "tenant_id", "engine_uid", "primary_key_field", "is_active"]}),
        ("Settings", {"fields": ["settings"], "classes": ["collapse"]}),
        ("Sync Status", {"fields": ["is_synced", "last_synced_at", "document_count"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
    ]


@admin.register(IndexSyncLog)
class IndexSyncLogAdmin(admin.ModelAdmin):
    list_display = ["index", "action", "status", "task_uid", "created_at", "completed_at"]
    list_filter = ["action", "status"]
    search_fields = ["index__name", "task_uid", "detail"]
    readonly_fields = [
        "index",
        "action",
        "status",
        "detail",
        "task_uid",
        "created_at",
        "completed_at",
    ]
    list_select_related = ["index"]


@admin.register(SearchQueryLog)
class SearchQueryLogAdmin(admin.ModelAdmin):
    list_display = [
        "query",
        "index_name",
        "hit_count",
        "is_zero_result",
        "processing_time_ms",
        "created_at",
    ]
    list_filter = ["is_zero_result", "index_name"]
    search_fields = ["query"]
    readonly_fields = [
        "index_name",
        "query",
        "filters",
        "sort",
        "hit_count",
        "processing_time_ms",
        "user",
        "tenant_id",
        "is_zero_result",
        "metadata",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SearchQueryAggregate)
class SearchQueryAggregateAdmin(admin.ModelAdmin):
    list_display = [
        "query",
        "index_name",
        "date",
        "tenant_id",
        "total_count",
        "zero_result_count",
        "get_avg_processing_time_ms",
    ]
    list_filter = ["index_name", "date"]
    search_fields = ["query"]
    date_hierarchy = "date"
    readonly_fields = [
        "index_name",
        "query",
        "date",
        "tenant_id",
        "total_count",
        "zero_result_count",
        "total_processing_time_ms",
        "created_at",
        "updated_at",
    ]

    @admin.display(description=_("avg processing time (ms)"))
    def get_avg_processing_time_ms(self, obj: SearchQueryAggregate) -> float:
        return obj.avg_processing_time_ms

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SearchClick)
class SearchClickAdmin(admin.ModelAdmin):
    list_display = [
        "query",
        "document_id",
        "index_name",
        "position",
        "tenant_id",
        "created_at",
    ]
    list_filter = ["index_name"]
    search_fields = ["query", "document_id"]
    readonly_fields = [
        "index_name",
        "query",
        "document_id",
        "position",
        "tenant_id",
        "metadata",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SearchClickAggregate)
class SearchClickAggregateAdmin(admin.ModelAdmin):
    list_display = [
        "query",
        "document_id",
        "index_name",
        "date",
        "click_count",
        "tenant_id",
    ]
    list_filter = ["index_name", "date"]
    search_fields = ["query", "document_id"]
    date_hierarchy = "date"
    readonly_fields = [
        "index_name",
        "query",
        "document_id",
        "date",
        "click_count",
        "tenant_id",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Shared bulk actions for all merchandising rule admins
# ---------------------------------------------------------------------------


@admin.action(description=_("Enable selected rules"))
def enable_rules(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description=_("Disable selected rules"))
def disable_rules(modeladmin, request, queryset):
    queryset.update(is_active=False)


# ---------------------------------------------------------------------------
# Merchandising rule admins
# ---------------------------------------------------------------------------


@admin.register(QueryRedirect)
class QueryRedirectAdmin(admin.ModelAdmin):
    list_display = [
        "query_pattern",
        "match_type",
        "destination_url",
        "destination_type",
        "http_status",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "match_type", "destination_type", "http_status"]
    search_fields = ["query_pattern", "destination_url"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (
            _("Destination"),
            {
                "fields": [
                    "destination_url",
                    "destination_type",
                    "preserve_query",
                    "http_status",
                ]
            },
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]


@admin.register(QueryRewrite)
class QueryRewriteAdmin(admin.ModelAdmin):
    list_display = [
        "query_pattern",
        "match_type",
        "rewritten_query",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "match_type"]
    search_fields = ["query_pattern", "rewritten_query"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "rewritten_query",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (
            _("Filters & Sort"),
            {
                "fields": ["apply_filters", "apply_sort", "merge_filters"],
                "classes": ["collapse"],
            },
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]


@admin.register(SearchPin)
class SearchPinAdmin(admin.ModelAdmin):
    list_display = [
        "query_pattern",
        "document_id",
        "position",
        "label",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "match_type"]
    search_fields = ["query_pattern", "document_id", "label"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "document_id",
                    "position",
                    "label",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]


@admin.register(BoostRule)
class BoostRuleAdmin(admin.ModelAdmin):
    list_display = [
        "query_pattern",
        "field",
        "operator",
        "field_value",
        "boost_weight",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "match_type", "operator"]
    search_fields = ["query_pattern", "field", "field_value"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (
            _("Boost Condition"),
            {"fields": ["field", "operator", "field_value", "boost_weight"]},
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]


@admin.register(SearchBanner)
class SearchBannerAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "query_pattern",
        "position",
        "banner_type",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "position", "banner_type"]
    search_fields = ["query_pattern", "title", "content"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (
            _("Content"),
            {"fields": ["title", "content", "image_url", "link_url", "link_text"]},
        ),
        (
            _("Display"),
            {
                "fields": ["position", "banner_type", "metadata"],
                "classes": ["collapse"],
            },
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]


@admin.register(ZeroResultFallback)
class ZeroResultFallbackAdmin(admin.ModelAdmin):
    list_display = [
        "query_pattern",
        "fallback_type",
        "fallback_value_truncated",
        "is_active",
        "priority",
        "hit_count",
    ]
    list_filter = ["is_active", "fallback_type"]
    search_fields = ["query_pattern", "fallback_value"]
    readonly_fields = ["hit_count", "created_at", "updated_at"]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "query_pattern",
                    "match_type",
                    "index_name",
                    "tenant_id",
                    "is_active",
                    "priority",
                ]
            },
        ),
        (
            _("Fallback Configuration"),
            {"fields": ["fallback_type", "fallback_value", "fallback_filters", "max_retries"]},
        ),
        (_("Schedule"), {"fields": ["starts_at", "ends_at"]}),
        (_("Statistics"), {"fields": ["hit_count"]}),
        (_("Timestamps"), {"fields": ["created_at", "updated_at"]}),
    ]
    actions = [enable_rules, disable_rules]

    @admin.display(description=_("fallback value"))
    def fallback_value_truncated(self, obj: ZeroResultFallback) -> str:
        value = obj.fallback_value
        if len(value) > 60:
            return f"{value[:60]}\u2026"
        return value
