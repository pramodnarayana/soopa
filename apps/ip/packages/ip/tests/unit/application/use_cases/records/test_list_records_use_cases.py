"""Zero-mock unit tests for ListNormalizedRecordsUseCase, ListGlobalEntityMapUseCase, ListReplicaRecordsUseCase, and ListInboundRecordsUseCase."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from ip.engine.application.use_cases.records.list_records_use_cases import (
    ListGlobalEntityMapQuery,
    ListGlobalEntityMapUseCase,
    ListInboundRecordsQuery,
    ListInboundRecordsUseCase,
    ListNormalizedRecordsQuery,
    ListNormalizedRecordsUseCase,
    ListReplicaRecordsQuery,
    ListReplicaRecordsUseCase,
)
from ip.engine.domain.exceptions import Result, TenantShardNotFoundError
from ip.engine.domain.normalization.normalized_record import GlobalEntityMap, NormalizedRecord
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord


class FakeNormalizedRepo:
    def __init__(self, records: Sequence[NormalizedRecord]) -> None:
        self._records = records
        self.last_query: dict[str, str | int | None] = {}

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        canonical_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[NormalizedRecord]:
        self.last_query = {
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "canonical_type": canonical_type,
            "limit": limit,
            "offset": offset,
        }
        return self._records


class FakeGemRepo:
    def __init__(self, entries: Sequence[GlobalEntityMap]) -> None:
        self._entries = entries
        self.last_query: dict[str, str | int | None] = {}

    async def list_entries(
        self,
        tenant_id: str,
        *,
        entity_domain: str | None = None,
        source_connection_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[GlobalEntityMap]:
        self.last_query = {
            "tenant_id": tenant_id,
            "entity_domain": entity_domain,
            "source_connection_id": source_connection_id,
            "limit": limit,
            "offset": offset,
        }
        return self._entries


class FakeReplicaRepo:
    def __init__(self, records: Sequence[ReplicaRecord]) -> None:
        self._records = records
        self.last_query: dict[str, str | int | None] = {}

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ReplicaRecord]:
        self.last_query = {
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "stream": stream,
            "limit": limit,
            "offset": offset,
        }
        return self._records


class FakeInboundRepo:
    def __init__(self, records: Sequence[InboundRecord]) -> None:
        self._records = records
        self.last_query: dict[str, str | int | bool | None] = {}

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        self.last_query = {
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "stream_name": stream_name,
            "limit": limit,
            "offset": offset,
            "hydrate_payloads": hydrate_payloads,
        }
        return self._records


class FakeDataPlaneUoW:
    def __init__(
        self,
        normalized_records: Sequence[NormalizedRecord] | None = None,
        gem_entries: Sequence[GlobalEntityMap] | None = None,
        replica_records: Sequence[ReplicaRecord] | None = None,
        inbound_records: Sequence[InboundRecord] | None = None,
    ) -> None:
        self.normalized_records = FakeNormalizedRepo(normalized_records or ())
        self.entity_maps = FakeGemRepo(gem_entries or ())
        self.replica_records = FakeReplicaRepo(replica_records or ())
        self.inbound_records = FakeInboundRepo(inbound_records or ())

    async def __aenter__(self) -> FakeDataPlaneUoW:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


class FakeUoWProvider:
    def __init__(
        self,
        uow: FakeDataPlaneUoW,
        shard_error: TenantShardNotFoundError | None = None,
    ) -> None:
        self._uow = uow
        self._shard_error = shard_error

    async def resolve_shard_info(
        self, tenant_id: str
    ) -> Result[tuple[str, str], TenantShardNotFoundError]:
        if self._shard_error is not None:
            return Result.err(self._shard_error)
        return Result.ok(("shard_01", "postgresql+asyncpg://localhost/test"))

    @asynccontextmanager
    async def get_data_plane_uow(
        self, tenant_id: str, shard_id: str, shard_dsn: str
    ) -> AsyncIterator[FakeDataPlaneUoW]:
        yield self._uow


@pytest.mark.asyncio
async def test_list_normalized_records_use_case_success() -> None:
    norm = NormalizedRecord(
        id="norm_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        connection_id="conn_01",
        canonical_type="METER",
        source_id="MTR-100",
        canonical_data={"serial": "MTR-100", "voltage": 240},
        normalized_at=datetime.now(UTC),
    )
    uow = FakeDataPlaneUoW(normalized_records=[norm])
    provider = FakeUoWProvider(uow)
    use_case = ListNormalizedRecordsUseCase(uow_provider=provider)

    res = await use_case.execute(
        ListNormalizedRecordsQuery(
            tenant_id="ten_01",
            connection_id="conn_01",
            canonical_type="METER",
            limit=25,
            offset=10,
        )
    )
    assert res.is_ok
    records = res.unwrap()
    assert len(records) == 1
    assert records[0].id == "norm_01"
    assert records[0].canonical_type == "METER"
    assert uow.normalized_records.last_query == {
        "tenant_id": "ten_01",
        "connection_id": "conn_01",
        "canonical_type": "METER",
        "limit": 25,
        "offset": 10,
    }


@pytest.mark.asyncio
async def test_list_gem_entries_use_case_success() -> None:
    gem = GlobalEntityMap(
        id="gem_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        entity_domain="METER",
        canonical_id="canon_01",
        source_connection_id="conn_itron",
        source_entity_id="MTR-100",
        dest_connection_id="conn_sap",
        dest_entity_id="SAP-EQ-100",
        created_at=datetime.now(UTC),
    )
    uow = FakeDataPlaneUoW(gem_entries=[gem])
    provider = FakeUoWProvider(uow)
    use_case = ListGlobalEntityMapUseCase(uow_provider=provider)

    res = await use_case.execute(
        ListGlobalEntityMapQuery(
            tenant_id="ten_01",
            entity_domain="METER",
            source_connection_id="conn_itron",
            limit=20,
            offset=5,
        )
    )
    assert res.is_ok
    entries = res.unwrap()
    assert len(entries) == 1
    assert entries[0].source_entity_id == "MTR-100"
    assert entries[0].dest_entity_id == "SAP-EQ-100"
    assert uow.entity_maps.last_query == {
        "tenant_id": "ten_01",
        "entity_domain": "METER",
        "source_connection_id": "conn_itron",
        "limit": 20,
        "offset": 5,
    }


@pytest.mark.asyncio
async def test_list_replica_records_use_case_success() -> None:
    replica = ReplicaRecord(
        id="rep_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meters",
        record_key="MTR-100",
        primary_key_values=("MTR-100",),
        data={"badge": "B123"},
        data_hash="abc",
        trace_id="trc_01",
    )
    uow = FakeDataPlaneUoW(replica_records=[replica])
    provider = FakeUoWProvider(uow)
    use_case = ListReplicaRecordsUseCase(uow_provider=provider)

    res = await use_case.execute(
        ListReplicaRecordsQuery(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream="meters",
            limit=15,
            offset=2,
        )
    )
    assert res.is_ok
    reps = res.unwrap()
    assert len(reps) == 1
    assert reps[0].record_key == "MTR-100"
    assert uow.replica_records.last_query == {
        "tenant_id": "ten_01",
        "connection_id": "conn_01",
        "stream": "meters",
        "limit": 15,
        "offset": 2,
    }


@pytest.mark.asyncio
async def test_list_inbound_records_use_case_success() -> None:
    inbound = InboundRecord(
        id="inb_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        connection_id="conn_01",
        app_id="itron",
        stream_name="meters",
        ingestion_mode=IngestionMode.PUSH_FULL,
        request_headers={"content-type": "application/json"},
        request_size_bytes=100,
        request_sha256="hash1",
        received_at=datetime.now(UTC),
    )
    uow = FakeDataPlaneUoW(inbound_records=[inbound])
    provider = FakeUoWProvider(uow)
    use_case = ListInboundRecordsUseCase(uow_provider=provider)

    res = await use_case.execute(
        ListInboundRecordsQuery(
            tenant_id="ten_01",
            connection_id="conn_01",
            stream_name="meters",
            limit=30,
            offset=4,
            hydrate_payloads=True,
        )
    )
    assert res.is_ok
    inbounds = res.unwrap()
    assert len(inbounds) == 1
    assert inbounds[0].id == "inb_01"
    assert uow.inbound_records.last_query == {
        "tenant_id": "ten_01",
        "connection_id": "conn_01",
        "stream_name": "meters",
        "limit": 30,
        "offset": 4,
        "hydrate_payloads": True,
    }


@pytest.mark.asyncio
async def test_records_use_case_handles_shard_error() -> None:
    uow = FakeDataPlaneUoW()
    err = TenantShardNotFoundError.for_tenant("ten_missing")
    provider = FakeUoWProvider(uow, shard_error=err)
    use_case = ListNormalizedRecordsUseCase(uow_provider=provider)

    res = await use_case.execute(ListNormalizedRecordsQuery(tenant_id="ten_missing"))
    assert res.is_err
    assert res.unwrap_err() == err
