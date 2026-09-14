from seedwork.domain.types import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.edi_settings import EdiSettings
from edi.ports.outbound.settings_repository import SettingsRepositoryPort


class SqlAlchemySettingsRepository(SettingsRepositoryPort):
    def __init__(self, global_session: AsyncSession):
        self.global_session = global_session

    async def get_config(self, key: str) -> JsonValue:
        stmt = select(EdiSettings).where(EdiSettings.key == key)
        result = await self.global_session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            return record.value
        return None

    async def set_config(self, key: str, value: JsonValue) -> None:
        stmt = select(EdiSettings).where(EdiSettings.key == key)
        result = await self.global_session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            record.value = value
        else:
            record = EdiSettings(key=key, value=value)
            self.global_session.add(record)
        await self.global_session.flush()
