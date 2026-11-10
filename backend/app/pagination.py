"""One paging rule for every list endpoint (performance.md > Pagination)."""

from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
# Far beyond any real list; it only stops an absurd page number from becoming an absurd OFFSET.
MAX_PAGE = 10_000


@dataclass(frozen=True)
class PageRequest:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_request(
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> PageRequest:
    """The `page` and `page_size` query parameters, checked at the boundary."""
    return PageRequest(page=page, page_size=page_size)


class Page[Item](BaseModel):
    """One page of a list, plus how many rows there are in total."""

    items: list[Item]
    total: int
    page: int
    page_size: int
