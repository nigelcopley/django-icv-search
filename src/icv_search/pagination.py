"""Search-aware pagination for Django views."""

from __future__ import annotations

import math

from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator

from icv_search.types import SearchResult


class ICVSearchPaginator(Paginator):
    """Paginator for search results that avoids a separate count query.

    Uses ``estimated_total_hits`` from the search engine response instead
    of calling ``queryset.count()``.  The hits are already sliced by the
    engine so the paginator simply wraps them for template consumption.

    Usage with a ListView or TemplateView::

        result = search("products", query, limit=25, offset=(page - 1) * 25)
        paginator = ICVSearchPaginator(result)
        page_obj = paginator.get_page(page)

    The paginator exposes ``is_estimated = True`` so templates can render
    "~1,200 results" instead of "1,200 results" when appropriate.
    """

    def __init__(
        self,
        search_result: SearchResult,
        per_page: int | None = None,
        orphans: int = 0,
        allow_empty_first_page: bool = True,
    ) -> None:
        self.search_result = search_result
        _per_page = per_page if per_page is not None else search_result.limit
        # Pass hits as the object_list — they are already the correct page slice
        super().__init__(
            object_list=search_result.hits,
            per_page=_per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    @property
    def count(self) -> int:
        """Return the total estimated hits from the search engine."""
        return self.search_result.estimated_total_hits

    @property
    def is_estimated(self) -> bool:
        """Whether the total count is an estimate (always True for search results)."""
        return True

    @property
    def num_pages(self) -> int:
        """Calculate number of pages from estimated total hits."""
        if self.count == 0 and not self.allow_empty_first_page:
            return 0
        hits = max(1, self.count - self.orphans)
        return math.ceil(hits / self.per_page)

    def page(self, number: int | str) -> ICVSearchPage:
        """Return the page for the given 1-based page number.

        Since hits are already sliced by the search engine, this wraps
        the existing hits rather than re-slicing.  If the estimate shifted
        and the page is now beyond the available results, returns an empty
        page instead of raising EmptyPage.
        """
        number = self.validate_number(number)
        return ICVSearchPage(self.search_result.hits, number, self)

    def validate_number(self, number: int | str) -> int:
        """Validate the page number, clamping to valid range.

        Overrides the base class to avoid raising EmptyPage when the
        estimate shifts — instead clamps to num_pages.
        """
        try:
            if isinstance(number, float) and not number.is_integer():
                raise ValueError
            number = int(number)
        except (TypeError, ValueError):
            raise PageNotAnInteger from None

        if number < 1:
            raise EmptyPage

        # Don't raise EmptyPage for page > num_pages — estimates can shift.
        # Clamp instead and return what we have (possibly empty hits).
        return number


class ICVSearchPage(Page):
    """A page of search results."""

    @property
    def is_estimated(self) -> bool:
        """Whether the total count is an estimate."""
        return self.paginator.is_estimated

    def display_count(self, prefix: str = "~") -> str:
        """Return a display-friendly count string.

        Returns "~1,200" for estimated counts, "1,200" for exact counts.
        """
        count = self.paginator.count
        if self.is_estimated:
            return f"{prefix}{count:,}"
        return f"{count:,}"
