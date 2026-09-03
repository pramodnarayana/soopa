from typing import Any

from typing import TypeAlias

JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | dict[str, JsonValue] | list[JsonValue]
type JsonDict = dict[str, JsonValue]


class UnsetType:
    """Singleton type for UNSET to distinguish from None."""

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Any = UnsetType()
