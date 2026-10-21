"""Strongly-typed DTOs and type aliases for shttp requests, query params, and JSON payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

import httpx
from seedwork import JsonDict, JsonPrimitive, JsonValue

__all__ = [
    "FormData",
    "FormDataPrimitive",
    "FormDataValue",
    "HttpRequest",
    "JsonDict",
    "JsonPrimitive",
    "JsonValue",
    "QueryParamPrimitive",
    "QueryParamValue",
    "QueryParams",
]

QueryParamPrimitive: TypeAlias = str | int | float | bool
QueryParamValue: TypeAlias = QueryParamPrimitive | Sequence[QueryParamPrimitive] | None
QueryParams: TypeAlias = Mapping[str, QueryParamValue]

FormDataPrimitive: TypeAlias = str | int | float | bool | bytes
FormDataValue: TypeAlias = FormDataPrimitive | Sequence[FormDataPrimitive] | None
FormData: TypeAlias = Mapping[str, FormDataValue]


@dataclass(frozen=True)
class HttpRequest:
    """Strongly-typed immutable command object representing an outbound HTTP request."""

    method: str
    url: str
    headers: Mapping[str, str] | None = None
    params: QueryParams | None = None
    data: FormData | None = None
    content: bytes | None = None
    json: JsonValue | None = None
    timeout: float | httpx.Timeout | None = None
