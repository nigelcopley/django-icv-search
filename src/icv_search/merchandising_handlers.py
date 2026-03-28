"""Signal handlers for merchandising rule cache invalidation.

Uses string sender references (e.g. ``"icv_search.QueryRedirect"``) to avoid
circular imports — models are resolved at signal dispatch time by Django.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

_RULE_MODELS = [
    "icv_search.QueryRedirect",
    "icv_search.QueryRewrite",
    "icv_search.SearchPin",
    "icv_search.BoostRule",
    "icv_search.SearchBanner",
    "icv_search.ZeroResultFallback",
]


def _invalidate_on_change(sender, instance, **kwargs):
    """Invalidate the merchandising rule cache when a rule is saved or deleted."""
    from icv_search.merchandising_cache import invalidate_rules

    rule_type = type(instance).__name__
    invalidate_rules(rule_type, instance.index_name, instance.tenant_id)
    logger.debug(
        "Invalidated %s cache for index=%s tenant=%s.",
        rule_type,
        instance.index_name,
        instance.tenant_id,
    )


for _model_label in _RULE_MODELS:
    receiver(post_save, sender=_model_label)(_invalidate_on_change)
    receiver(post_delete, sender=_model_label)(_invalidate_on_change)
