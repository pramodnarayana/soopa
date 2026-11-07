"""Application use-case unit tests for ReplayStageUseCase, ModifyAndReplayUseCase, and BulkReplayStageUseCase."""

from __future__ import annotations

import pytest
from helpers.trace_fakes import InMemoryDataPlaneUoW, InMemoryDataPlaneUoWProvider
from ip.engine.application.use_cases.replay.bulk_replay_stage_use_case import (
    BulkReplayStageCommand,
    BulkReplayStageUseCase,
)
from ip.engine.application.use_cases.replay.modify_and_replay_use_case import (
    ModifyAndReplayCommand,
    ModifyAndReplayUseCase,
)
from ip.engine.application.use_cases.replay.replay_stage_use_case import (
    ReplayStage,
    ReplayStageCommand,
    ReplayStageUseCase,
)
from ip.engine.bootstrap.container import create_default_stage_replay_processors
from ip.engine.domain.dispatch.enums import HttpWriteOperation
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.enums import PipelineStage
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.domain.normalization.normalized_record import NormalizedRecord
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.replica_record import ReplicaRecord


async def _seed_pipeline_trace_records(uow: InMemoryDataPlaneUoW) -> None:
    inb = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-100","quantity":42.5}',
        is_inlined=True,
        trace_id="ip_trc_root",
        correlation_id="REC-100",
        request_body={"record_id": "REC-100", "quantity": 42.5},
    )
    rep = ReplicaRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="records_alpha",
        primary_key_values=("REC-100",),
        data={"record_id": "REC-100", "quantity": 42.5},
        trace_id="ip_trc_root",
        correlation_id="REC-100",
    )
    nrm = NormalizedRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type="canonical.record_alpha",
        source_id="REC-100",
        canonical_data={"record_id": "REC-100", "normalized_quantity": 42.5},
        trace_id="ip_trc_root",
        correlation_id="REC-100",
    )
    out = OutboundRecord.create_pending(
        tenant_id="ten_01",
        connection_id="conn_dest_01",
        app_id="partner_erp",
        stream_name="invoices",
        target_url="https://api.erp.example.com/v1/invoices",
        http_method="POST",
        payload_bytes=b'{"record_id":"REC-100"}',
        is_inlined=True,
        trace_id="ip_trc_root",
        operation=HttpWriteOperation.CREATE.value,
        correlation_id="REC-100",
        request_body={"record_id": "REC-100"},
    )
    out.mark_failed(error_message="HTTP 503 Unavailable", response_status_code=503)

    await uow.inbound_records.save(inb)
    await uow.replica_records.save(rep)
    await uow.normalized_records.save(nrm)
    await uow.outbound_records.save(out)


@pytest.mark.asyncio
async def test_replay_stage_use_case_replays_delivery_from_root_trace() -> None:
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    deliv_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_DELIVER,
            actor="ops@soopa.io",
        )
    )
    assert deliv_res.is_ok
    deliv_dto = deliv_res.unwrap()
    assert deliv_dto.original_trace_id == "ip_trc_root"
    assert deliv_dto.parent_trace_id == "ip_trc_root"
    assert deliv_dto.replay_count == 1
    assert deliv_dto.stage == ReplayStage.RETRY_DELIVER


@pytest.mark.asyncio
async def test_replay_stage_use_case_hydrates_upstream_normalized_record_across_parent_lineage() -> (
    None
):
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    deliv_dto = (
        await replay_uc.execute(
            ReplayStageCommand(
                tenant_id="ten_01",
                trace_id="ip_trc_root",
                stage=ReplayStage.RETRY_DELIVER,
                actor="ops@soopa.io",
            )
        )
    ).unwrap()

    stitch_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id=deliv_dto.new_trace_id,
            stage=ReplayStage.RETRY_STITCH,
            actor="ops@soopa.io",
        )
    )
    assert stitch_res.is_ok
    stitch_dto = stitch_res.unwrap()
    assert stitch_dto.original_trace_id == "ip_trc_root"
    assert stitch_dto.parent_trace_id == deliv_dto.new_trace_id
    assert stitch_dto.replay_count == 2


@pytest.mark.asyncio
async def test_replay_stage_use_case_replays_ingest_stage() -> None:
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    ingest_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_INGEST,
            actor="ops@soopa.io",
        )
    )
    assert ingest_res.is_ok
    assert ingest_res.unwrap().stage == ReplayStage.RETRY_INGEST


@pytest.mark.asyncio
async def test_replay_stage_use_case_replays_normalize_stage() -> None:
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    norm_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=ReplayStage.RETRY_NORMALIZE,
            actor="ops@soopa.io",
        )
    )
    assert norm_res.is_ok
    assert norm_res.unwrap().stage == ReplayStage.RETRY_NORMALIZE


@pytest.mark.asyncio
async def test_replay_stage_use_case_accepts_pipeline_stage_enum_alias() -> None:
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    pipeline_stage_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=PipelineStage.INGEST,
            actor="ops@soopa.io",
        )
    )
    assert pipeline_stage_res.is_ok
    assert pipeline_stage_res.unwrap().stage == ReplayStage.RETRY_INGEST


@pytest.mark.asyncio
async def test_replay_stage_use_case_rejects_non_executable_replica_stage() -> None:
    uow = InMemoryDataPlaneUoW()
    await _seed_pipeline_trace_records(uow)
    replay_uc = ReplayStageUseCase(
        uow_provider=InMemoryDataPlaneUoWProvider(uow),
        stage_processors=create_default_stage_replay_processors(),
    )

    non_exec_res = await replay_uc.execute(
        ReplayStageCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_root",
            stage=PipelineStage.REPLICA,
            actor="ops@soopa.io",
        )
    )
    assert non_exec_res.is_err
    assert non_exec_res.unwrap_err().code == IpErrorCode.REPLAY_STAGE_NOT_AVAILABLE


@pytest.mark.asyncio
async def test_modify_replay_use_case_rejects_empty_payload() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    processors = create_default_stage_replay_processors()
    modify_uc = ModifyAndReplayUseCase(uow_provider=provider, stage_processors=processors)

    inb1 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-101","quantity":10.0}',
        is_inlined=True,
        trace_id="ip_trc_m1",
        correlation_id="REC-101",
        request_body={"record_id": "REC-101", "quantity": 10.0},
    )
    await uow.inbound_records.save(inb1)

    bad_mod = await modify_uc.execute(
        ModifyAndReplayCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_m1",
            stage=ReplayStage.RETRY_INGEST,
            modified_payload={},
            actor="support@soopa.io",
        )
    )
    assert bad_mod.is_err
    assert bad_mod.unwrap_err().code == IpErrorCode.INVALID_REPLAY_PAYLOAD


@pytest.mark.asyncio
async def test_modify_replay_use_case_replays_modified_inbound_payload() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    processors = create_default_stage_replay_processors()
    modify_uc = ModifyAndReplayUseCase(uow_provider=provider, stage_processors=processors)

    inb1 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-101","quantity":10.0}',
        is_inlined=True,
        trace_id="ip_trc_m1",
        correlation_id="REC-101",
        request_body={"record_id": "REC-101", "quantity": 10.0},
    )
    await uow.inbound_records.save(inb1)

    good_mod = await modify_uc.execute(
        ModifyAndReplayCommand(
            tenant_id="ten_01",
            trace_id="ip_trc_m1",
            stage=ReplayStage.RETRY_INGEST,
            modified_payload={"record_id": "REC-101", "quantity": 99.9},
            actor="support@soopa.io",
        )
    )
    assert good_mod.is_ok
    mod_dto = good_mod.unwrap()
    replayed_inb = await uow.inbound_records.get_by_trace_id(mod_dto.new_trace_id, "ten_01")
    assert len(replayed_inb) == 1
    assert replayed_inb[0].request_body == {"record_id": "REC-101", "quantity": 99.9}


@pytest.mark.asyncio
async def test_bulk_replay_stage_use_case_deduplicates_traces_with_partial_failures() -> None:
    uow = InMemoryDataPlaneUoW()
    provider = InMemoryDataPlaneUoWProvider(uow)
    processors = create_default_stage_replay_processors()
    bulk_uc = BulkReplayStageUseCase(uow_provider=provider, stage_processors=processors)

    inb1 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-101","quantity":10.0}',
        is_inlined=True,
        trace_id="ip_trc_m1",
        correlation_id="REC-101",
        request_body={"record_id": "REC-101", "quantity": 10.0},
    )
    inb2 = InboundRecord.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="acme_source",
        stream_name="records_alpha",
        payload_bytes=b'{"record_id":"REC-102","quantity":20.0}',
        is_inlined=True,
        trace_id="ip_trc_m2",
        correlation_id="REC-102",
        request_body={"record_id": "REC-102", "quantity": 20.0},
    )
    await uow.inbound_records.save(inb1)
    await uow.inbound_records.save(inb2)

    bulk_res = await bulk_uc.execute(
        BulkReplayStageCommand(
            tenant_id="ten_01",
            trace_ids=("ip_trc_m1", "ip_trc_m1", "ip_trc_m2", "ip_trc_nonexistent"),
            stage=ReplayStage.RETRY_INGEST,
            actor="ops@soopa.io",
        )
    )
    assert bulk_res.is_ok
    bulk_dto = bulk_res.unwrap()
    assert bulk_dto.replayed_count == 2
    assert bulk_dto.succeeded_trace_ids == ("ip_trc_m1", "ip_trc_m2")
    assert len(bulk_dto.new_trace_ids) == 2
    assert len(bulk_dto.failed_items) == 1
    assert bulk_dto.failed_items[0].trace_id == "ip_trc_nonexistent"
