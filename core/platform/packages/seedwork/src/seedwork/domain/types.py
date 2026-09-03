from typing import TYPE_CHECKING, Any, TypeAlias

from typing_extensions import TypeAliasType

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


UNSET: Any = UnsetType()
