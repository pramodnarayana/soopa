"""Canonical type aliases for the Integration Platform bounded context."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from typing_extensions import TypeAliasType

JsonPrimitive: TypeAlias = str | int | float | bool | None

if TYPE_CHECKING:
    JsonValue: TypeAlias = JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]
    JsonDict: TypeAlias = dict[str, JsonValue]
else:
    JsonValue = TypeAliasType(
        "JsonValue", JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]
    )
    JsonDict = TypeAliasType("JsonDict", dict[str, JsonValue])
