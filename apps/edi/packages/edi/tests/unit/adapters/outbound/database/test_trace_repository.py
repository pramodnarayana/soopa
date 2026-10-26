from typing import cast

import pytest
from database.types import TenantSession
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.transaction_repository import SqlAlchemyTransactionRepository


class UnusedStorage:
    async def download(self, uri: str) -> bytes:
        raise AssertionError(f"Unexpected download: {uri}")

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        raise AssertionError("Unexpected upload")


class EmptyScalars:
    def first(self) -> None:
        return None

    def all(self) -> list[object]:
        return []


class EmptyResult:
    def scalars(self) -> EmptyScalars:
        return EmptyScalars()


class RecordingSession:
    def __init__(self) -> None:
        self.info: dict[str, str] = {"session_type": "tenant"}
        self.statements: list[object] = []

    async def execute(self, statement: object) -> EmptyResult:
        self.statements.append(statement)
        return EmptyResult()


@pytest.mark.asyncio
async def test_get_edi_message_dto_selects_only_the_newest_edi_message() -> None:
    session = RecordingSession()
    repository = SqlAlchemyTransactionRepository(
        TenantSession(cast(AsyncSession, session)),
        UnusedStorage(),
    )

    assert await repository.get_edi_message_dto("tenant-1", "trace-1") is None

    compiled = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "ORDER BY edi_messages.created_at DESC" in compiled
    assert "LIMIT 1" in compiled
