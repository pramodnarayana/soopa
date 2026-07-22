from typing import Any

from api.ports.platform_settings_repository import PlatformSettingsRepositoryPort
from database.models.platform_settings import PlatformSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyPlatformSettingsRepository(PlatformSettingsRepositoryPort):
    def __init__(self, global_session: AsyncSession):
        self.global_session = global_session

    async def get_config(self, key: str) -> Any | None:
        stmt = select(PlatformSettings).where(PlatformSettings.key == key)
        result = await self.global_session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            return record.value
        return None

    async def set_config(self, key: str, value: Any) -> None:
        stmt = select(PlatformSettings).where(PlatformSettings.key == key)
        result = await self.global_session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            record.value = value
        else:
            record = PlatformSettings(key=key, value=value)
            self.global_session.add(record)
        await self.global_session.flush()
