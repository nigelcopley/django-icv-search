"""Signal definitions for icv-search."""

from django.dispatch import Signal

# Fired after a new SearchIndex is created and its engine index provisioned
search_index_created = Signal()

# Fired after a SearchIndex and its engine index are deleted
search_index_deleted = Signal()

# Fired after index settings are successfully pushed to the engine
search_index_synced = Signal()

# Fired after documents are added/updated in the engine
# Provides: instance, count, document_ids
documents_indexed = Signal()

# Fired after documents are removed from the engine
# Provides: instance, count, document_ids
documents_removed = Signal()
