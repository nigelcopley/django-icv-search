"""Search service functions — the public API of icv-search."""

from icv_search.auto_index import skip_index_update
from icv_search.cache import ICVSearchCache
from icv_search.middleware import get_current_tenant_id
from icv_search.services.analytics import (
    clear_query_aggregates,
    clear_query_logs,
    get_popular_queries,
    get_query_trend,
    get_search_stats,
    get_zero_result_queries,
)
from icv_search.services.banners import get_banners_for_query
from icv_search.services.boosts import apply_boosts, get_boost_rules_for_query
from icv_search.services.click_tracking import (
    get_click_through_rate,
    get_top_clicked_documents,
    log_click,
)
from icv_search.services.discovery import (
    facet_search,
    similar_documents,
)
from icv_search.services.documents import (
    bulk_index,
    delete_document,
    get_document,
    get_documents,
    index_documents,
    index_model_instances,
    reindex_all,
    reindex_zero_downtime,
    remove_documents,
    update_documents,
)
from icv_search.services.fallbacks import execute_fallback, get_fallback_for_query
from icv_search.services.indexing import (
    compact_index,
    create_index,
    delete_index,
    get_index_settings,
    get_index_stats,
    get_model_search_settings,
    get_stop_words,
    get_synonyms,
    get_typo_tolerance,
    reset_stop_words,
    reset_synonyms,
    update_index_settings,
    update_stop_words,
    update_synonyms,
    update_typo_tolerance,
)
from icv_search.services.intelligence import (
    auto_create_rewrites,
    cluster_queries,
    get_demand_signals,
    suggest_synonyms,
)
from icv_search.services.merchandising import merchandised_search
from icv_search.services.pins import apply_pins, get_pins_for_query
from icv_search.services.preprocessing import load_preprocessor, preprocess, reset_preprocessor
from icv_search.services.redirects import check_redirect, resolve_redirect_url
from icv_search.services.rewrites import apply_rewrite
from icv_search.services.search import autocomplete, get_task, multi_search, search
from icv_search.services.suggestions import get_suggested_queries, get_trending_searches
from icv_search.types import IndexStats, MerchandisedSearchResult, SearchResult, TaskResult

__all__ = [
    # Index management
    "create_index",
    "delete_index",
    "update_index_settings",
    "get_index_settings",
    "get_index_stats",
    "get_model_search_settings",
    "compact_index",
    # Synonym management
    "get_synonyms",
    "update_synonyms",
    "reset_synonyms",
    # Stop-word management
    "get_stop_words",
    "update_stop_words",
    "reset_stop_words",
    # Typo tolerance
    "get_typo_tolerance",
    "update_typo_tolerance",
    # Document operations
    "index_documents",
    "remove_documents",
    "delete_document",
    "get_document",
    "get_documents",
    "update_documents",
    "index_model_instances",
    "bulk_index",
    "reindex_all",
    "reindex_zero_downtime",
    # Discovery
    "facet_search",
    "similar_documents",
    # Search
    "search",
    "autocomplete",
    "multi_search",
    "get_task",
    # Merchandising pipeline
    "merchandised_search",
    "MerchandisedSearchResult",
    # Merchandising — redirects
    "check_redirect",
    "resolve_redirect_url",
    # Merchandising — rewrites
    "apply_rewrite",
    # Merchandising — pins
    "get_pins_for_query",
    "apply_pins",
    # Merchandising — boosts
    "get_boost_rules_for_query",
    "apply_boosts",
    # Merchandising — banners
    "get_banners_for_query",
    # Merchandising — fallbacks
    "get_fallback_for_query",
    "execute_fallback",
    # Suggestions
    "get_trending_searches",
    "get_suggested_queries",
    # Utilities
    "skip_index_update",
    # Tenant context
    "get_current_tenant_id",
    # Cache
    "ICVSearchCache",
    # Normalised response types
    "IndexStats",
    "SearchResult",
    "TaskResult",
    # Analytics
    "get_popular_queries",
    "get_zero_result_queries",
    "get_search_stats",
    "clear_query_logs",
    "get_query_trend",
    "clear_query_aggregates",
    # Click tracking
    "log_click",
    "get_click_through_rate",
    "get_top_clicked_documents",
    # Query preprocessing
    "load_preprocessor",
    "preprocess",
    "reset_preprocessor",
    # Search intelligence
    "get_demand_signals",
    "cluster_queries",
    "suggest_synonyms",
    "auto_create_rewrites",
]
