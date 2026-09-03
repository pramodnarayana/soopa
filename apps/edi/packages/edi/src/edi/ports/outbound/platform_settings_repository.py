import abc

from seedwork.domain.types import JsonValue


class PlatformSettingsRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def get_config(self, key: str) -> JsonValue | None:
        pass

    @abc.abstractmethod
    async def set_config(self, key: str, value: JsonValue) -> None:
        pass
