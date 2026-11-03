from typing import TYPE_CHECKING, TypeAlias, TypeVar

from typing_extensions import TypeAliasType

_T = TypeVar("_T")

JsonPrimitive = str | int | float | bool | None
if TYPE_CHECKING:
    JsonValue: TypeAlias = JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]
    JsonDict: TypeAlias = dict[str, JsonValue]
else:
    JsonValue = TypeAliasType(
        "JsonValue", JsonPrimitive | dict[str, "JsonValue"] | list["JsonValue"]
    )
    JsonDict = TypeAliasType("JsonDict", dict[str, JsonValue])


class UnsetType:
    """Singleton type for UNSET to distinguish from None."""

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: UnsetType = UnsetType()


def resolve_unset(candidate: _T | UnsetType, current: _T) -> _T:
    """Return ``current`` when ``candidate`` is ``UNSET``, otherwise ``candidate``."""
    if isinstance(candidate, UnsetType):
        return current
    return candidate


def resolve_defined(candidate: _T | UnsetType | None, current: _T) -> _T:
    """Return ``current`` when ``candidate`` is ``UNSET`` or ``None``, otherwise ``candidate``."""
    if isinstance(candidate, UnsetType) or candidate is None:
        return current
    return candidate
