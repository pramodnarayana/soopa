import abc
from typing import Any


class PlatformSettingsRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def get_config(self, key: str) -> Any | None:
        pass

    @abc.abstractmethod
    async def set_config(self, key: str, value: Any) -> None:
        pass
