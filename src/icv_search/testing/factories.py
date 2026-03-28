"""Factory-boy factories for icv-search models."""

import datetime

import factory
import factory.fuzzy

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


class SearchIndexFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchIndex

    name = factory.Sequence(lambda n: f"test-index-{n}")
    tenant_id = ""
    primary_key_field = "id"
    settings = factory.LazyFunction(dict)
    is_active = True


class IndexSyncLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = IndexSyncLog

    index = factory.SubFactory(SearchIndexFactory)
    action = "created"
    status = "success"


class SearchQueryLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchQueryLog

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query = factory.Sequence(lambda n: f"test query {n}")
    filters = factory.LazyFunction(dict)
    sort = factory.LazyFunction(list)
    hit_count = 5
    processing_time_ms = 10
    user = None
    tenant_id = ""
    is_zero_result = False
    metadata = factory.LazyFunction(dict)


class SearchQueryAggregateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchQueryAggregate

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query = factory.Sequence(lambda n: f"test query {n}")
    date = factory.LazyFunction(datetime.date.today)
    tenant_id = ""
    total_count = 10
    zero_result_count = 2
    total_processing_time_ms = 150


class QueryRedirectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QueryRedirect

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"redirect query {n}")
    match_type = "exact"
    destination_url = factory.Sequence(lambda n: f"https://example.com/redirect/{n}")
    destination_type = "url"
    preserve_query = False
    http_status = 302
    is_active = True
    priority = 0


class QueryRewriteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QueryRewrite

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"rewrite query {n}")
    match_type = "exact"
    rewritten_query = factory.Sequence(lambda n: f"rewritten {n}")
    apply_filters = factory.LazyFunction(dict)
    apply_sort = factory.LazyFunction(list)
    merge_filters = True
    is_active = True
    priority = 0


class SearchPinFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchPin

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"pin query {n}")
    match_type = "exact"
    document_id = factory.Sequence(lambda n: f"doc-{n}")
    position = 0
    label = ""
    is_active = True
    priority = 0


class BoostRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BoostRule

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"boost query {n}")
    match_type = "exact"
    field = "category"
    field_value = "featured"
    operator = "eq"
    boost_weight = factory.LazyFunction(lambda: __import__("decimal").Decimal("2.000"))
    is_active = True
    priority = 0


class SearchBannerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchBanner

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"banner query {n}")
    match_type = "exact"
    title = factory.Sequence(lambda n: f"Banner {n}")
    content = ""
    position = "top"
    banner_type = "informational"
    metadata = factory.LazyFunction(dict)
    is_active = True
    priority = 0


class ZeroResultFallbackFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ZeroResultFallback

    index_name = factory.Sequence(lambda n: f"test-index-{n}")
    query_pattern = factory.Sequence(lambda n: f"fallback query {n}")
    match_type = "exact"
    fallback_type = "alternative_query"
    fallback_value = "popular items"
    fallback_filters = factory.LazyFunction(dict)
    max_retries = 1
    is_active = True
    priority = 0


class SearchClickFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchClick

    index_name = "products"
    query = factory.Sequence(lambda n: f"query {n}")
    document_id = factory.Sequence(lambda n: f"prod-{n}")
    position = factory.fuzzy.FuzzyInteger(0, 9)
    tenant_id = ""
    metadata = factory.LazyFunction(dict)


class SearchClickAggregateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SearchClickAggregate

    index_name = "products"
    query = factory.Sequence(lambda n: f"query {n}")
    document_id = factory.Sequence(lambda n: f"prod-{n}")
    date = factory.LazyFunction(datetime.date.today)
    click_count = 5
    tenant_id = ""
