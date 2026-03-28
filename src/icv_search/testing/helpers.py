"""Test helper functions for icv-search."""

from icv_search.backends.dummy import _documents, _indexes


def get_indexed_documents(index_uid: str) -> list[dict]:
    """Return all documents in the dummy backend for a given index."""
    return list(_documents.get(index_uid, {}).values())


def get_dummy_indexes() -> dict:
    """Return all indexes in the dummy backend."""
    return dict(_indexes)


def assert_document_indexed(index_uid: str, doc_id: str) -> None:
    """Assert that a document exists in the dummy backend."""
    docs = _documents.get(index_uid, {})
    assert str(doc_id) in docs, f"Document {doc_id} not found in index {index_uid}. Found: {list(docs.keys())}"


class MockPreprocessor:
    """Test helper — records calls and returns configurable results.

    Usage::

        from icv_search.testing.helpers import MockPreprocessor
        from icv_search.types import PreprocessedQuery

        mock = MockPreprocessor(result=PreprocessedQuery(
            query="waterproof shoes",
            extracted_filters={"price__lte": 60},
            intent="product_search",
        ))

        # Patch _preprocessor_callable directly or use override_settings
        assert len(mock.calls) == 1
    """

    def __init__(self, result=None):
        from icv_search.types import PreprocessedQuery

        self.calls = []
        self.result = result or PreprocessedQuery(query="")

    def __call__(self, query, context):
        from icv_search.types import PreprocessedQuery

        self.calls.append((query, context))
        if not self.result.query:
            return PreprocessedQuery(query=query)
        return self.result
