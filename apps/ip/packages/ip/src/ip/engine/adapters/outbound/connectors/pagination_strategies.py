"""Pluggable pagination strategies for GenericHttpConnector."""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from ip.engine.domain.enums import PaginationType
from seedwork.domain.types import JsonDict, JsonValue


class PaginationStrategy(Protocol):
    """Protocol for resolving the next page request parameters or URL."""

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        """Returns updated query parameters for the next page, or None if iteration is complete."""
        ...


def _extract_nested(data: JsonValue, path: list[str] | tuple[str, ...]) -> JsonValue:
    curr = data
    for key in path:
        if not isinstance(curr, dict) or key not in curr:
            return None
        curr = curr[key]
    return curr


class NonePaginationStrategy(PaginationStrategy):
    """Single page execution; never requests a second page."""

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        return None


class CursorPaginationStrategy(PaginationStrategy):
    """Cursor-based pagination extracting token from response body."""

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        raw_cursor_path = pagination_params.get("cursor_path")
        cursor_param = str(pagination_params.get("cursor_param", "cursor"))

        if isinstance(raw_cursor_path, str):
            cursor_path: list[str] | tuple[str, ...] = raw_cursor_path.split(".")
        elif isinstance(raw_cursor_path, (list, tuple)):
            cursor_path = [str(part) for part in raw_cursor_path]
        else:
            cursor_path = ["next_cursor"]

        token = _extract_nested(last_response_data, cursor_path)
        if not token:
            return None

        # Check if stop_value configured
        stop_val = pagination_params.get("stop_value")
        if stop_val is not None and token == stop_val:
            return None

        next_params = dict(current_query_params)
        next_params[cursor_param] = str(token)
        return next_params


class OffsetLimitPaginationStrategy(PaginationStrategy):
    """Offset-limit pagination advancing offset by page size until exhaust."""

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        limit_param = str(pagination_params.get("limit_param", "limit"))
        offset_param = str(pagination_params.get("offset_param", "offset"))
        raw_limit = pagination_params.get("limit", current_query_params.get(limit_param, 50))
        limit = int(raw_limit) if isinstance(raw_limit, (int, float, str)) else 50

        # If zero records returned or fewer than limit, end of stream
        if records_in_page == 0 or records_in_page < limit:
            return None

        current_offset = int(current_query_params.get(offset_param, 0))
        next_offset = current_offset + limit

        next_params = dict(current_query_params)
        next_params[offset_param] = str(next_offset)
        next_params[limit_param] = str(limit)
        return next_params


class PageNumberPaginationStrategy(PaginationStrategy):
    """Page number pagination incrementing page index on each request."""

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        page_param = str(pagination_params.get("page_param", "page"))
        page_size_param = str(pagination_params.get("page_size_param", "page_size"))
        raw_page_start = pagination_params.get("page_start", 1)
        page_start = int(raw_page_start) if isinstance(raw_page_start, (int, float, str)) else 1
        raw_page_size = pagination_params.get(
            "page_size", current_query_params.get(page_size_param, 50)
        )
        page_size = int(raw_page_size) if isinstance(raw_page_size, (int, float, str)) else 50

        if records_in_page == 0:
            return None

        current_page = int(current_query_params.get(page_param, page_start + page_index))
        next_page = current_page + 1

        next_params = dict(current_query_params)
        next_params[page_param] = str(next_page)
        if page_size_param in current_query_params or "page_size" in pagination_params:
            next_params[page_size_param] = str(page_size)
        return next_params


class LinkHeaderPaginationStrategy(PaginationStrategy):
    """RFC 5988 Link header pagination extracting 'rel=next' target URL."""

    _LINK_RE = re.compile(r'<([^>]+)>;\s*rel=["\']?next["\']?', re.IGNORECASE)

    def get_next_page(
        self,
        *,
        current_query_params: dict[str, str],
        last_response_data: JsonValue,
        last_response_headers: dict[str, str],
        page_index: int,
        records_in_page: int,
        pagination_params: JsonDict,
    ) -> dict[str, str] | None:
        link_header = last_response_headers.get("link") or last_response_headers.get("Link")
        if not link_header:
            return None

        match = self._LINK_RE.search(link_header)
        if not match:
            return None

        next_url = match.group(1)
        # Parse query params from next_url
        parsed = urlparse(next_url)
        parsed_qs = parse_qs(parsed.query)

        next_params = dict(current_query_params)
        for k, v in parsed_qs.items():
            if v:
                next_params[k] = v[0]
        return next_params


class PaginationStrategyResolver:
    """Resolves concrete PaginationStrategy implementations by PaginationType."""

    _STRATEGIES: dict[PaginationType, PaginationStrategy] = {
        PaginationType.NONE: NonePaginationStrategy(),
        PaginationType.CURSOR: CursorPaginationStrategy(),
        PaginationType.OFFSET_LIMIT: OffsetLimitPaginationStrategy(),
        PaginationType.PAGE_NUMBER: PageNumberPaginationStrategy(),
        PaginationType.LINK_HEADER: LinkHeaderPaginationStrategy(),
    }

    @classmethod
    def resolve(cls, pagination_type: PaginationType) -> PaginationStrategy:
        return cls._STRATEGIES.get(pagination_type, cls._STRATEGIES[PaginationType.NONE])
