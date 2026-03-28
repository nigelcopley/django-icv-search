"""Search-specific exceptions."""


class IcvSearchError(Exception):
    """Base exception for all icv-search errors."""


class SearchBackendError(IcvSearchError):
    """Raised when a backend operation fails."""

    def __init__(self, message: str, original_exception: Exception | None = None):
        super().__init__(message)
        self.original_exception = original_exception


class IndexNotFoundError(IcvSearchError):
    """Raised when a search index cannot be found."""


class SearchTimeoutError(SearchBackendError):
    """Raised when a backend operation times out."""
