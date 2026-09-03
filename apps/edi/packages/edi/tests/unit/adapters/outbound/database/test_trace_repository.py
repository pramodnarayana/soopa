from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.trace_repository import SqlAlchemyTraceRepository


class UnusedStorage:
    async def download(self, uri: str) -> bytes:
        raise AssertionError(f"Unexpected download: {uri}")

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        raise AssertionError("Unexpected upload")


class EmptyScalars:
    def first(self) -> None:
        return None


class EmptyResult:
    def scalars(self) -> EmptyScalars:
        return EmptyScalars()


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> EmptyResult:
        self.statements.append(statement)
        return EmptyResult()


@pytest.mark.asyncio
async def test_trace_selects_only_the_newest_edi_message() -> None:
    session = RecordingSession()
    repository = SqlAlchemyTraceRepository(cast(AsyncSession, session), UnusedStorage())

    assert await repository.get_edi_trace("tenant-1", "trace-1") is None

    compiled = str(
        session.statements[0].compile(compile_kwargs={"literal_binds": True})  # type: ignore[attr-defined]
    )
    assert "ORDER BY edi.edi_messages.created_at DESC" in compiled
    assert "LIMIT 1" in compiled
