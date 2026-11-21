"""Unit tests for Universal Platform Replay Coordinator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from replay import (
    ExecuteReplayCommandDTO,
    ReplayPreviewRequestDTO,
    ReplayPreviewResponseDTO,
    ReplayStage,
    ReplayStatus,
    ReplayTargetType,
    StageReplayProcessorPort,
    UniversalReplayCoordinator,
    UnsupportedReplayStageError,
)
from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict


class FakeDomainStageProcessor(StageReplayProcessorPort):
    def __init__(self, stage: ReplayStage, should_succeed: bool = True) -> None:
        self.stage = stage
        self.should_succeed = should_succeed
        self.replayed_targets: list[tuple[str, str, str, str]] = []

    async def preview_replay(
        self,
        tenant_id: str,
        target_id: str,
        modified_payload: JsonDict | None = None,
    ) -> Result[ReplayPreviewResponseDTO, Exception]:
        return Result.ok(
            ReplayPreviewResponseDTO(
                target_id=target_id,
                target_type=ReplayTargetType.BATCH,
                target_stage=self.stage,
                affected_entity_count=50,
                total_record_count=1200,
                window_start_utc=datetime(2026, 11, 20, 0, 0, tzinfo=UTC),
                window_end_utc=datetime(2026, 11, 20, 1, 0, tzinfo=UTC),
                estimated_duration_seconds=1.5,
                will_deliver_to_egress=self.stage == ReplayStage.STAGE_4_WIRE_EGRESS,
                requires_idempotency_key=True,
            )
        )

    async def replay_stage(
        self,
        tenant_id: str,
        target_id: str,
        new_trace_id: str,
        parent_trace_id: str,
        is_replay: bool = True,
        modified_payload: JsonDict | None = None,
    ) -> Result[bool, Exception]:
        if not self.should_succeed:
            return Result.fail(RuntimeError("Simulated pipeline failure"))
        self.replayed_targets.append((tenant_id, target_id, new_trace_id, parent_trace_id))
        return Result.ok(True)


@pytest.mark.asyncio
async def test_replay_coordinator_preview_and_execute_success() -> None:
    coordinator = UniversalReplayCoordinator()
    raw_proc = FakeDomainStageProcessor(ReplayStage.STAGE_1_RAW_INGRESS)
    egress_proc = FakeDomainStageProcessor(ReplayStage.STAGE_4_WIRE_EGRESS)

    coordinator.register_processor(raw_proc)
    coordinator.register_processor(egress_proc)

    # 1. Preview
    preview_req = ReplayPreviewRequestDTO(
        target_id="bat_001",
        tenant_id="utility_bescom",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
        target_type=ReplayTargetType.BATCH,
    )
    preview_res = await coordinator.preview(preview_req)
    assert preview_res.is_ok
    preview = preview_res.unwrap()
    assert preview.total_record_count == 1200
    assert preview.target_stage == ReplayStage.STAGE_1_RAW_INGRESS
    assert not preview.will_deliver_to_egress

    # 2. Execute
    exec_cmd = ExecuteReplayCommandDTO(
        target_id="bat_001",
        tenant_id="utility_bescom",
        target_stage=ReplayStage.STAGE_1_RAW_INGRESS,
        actor="sre_operator",
        reason="VEE rule updated after meter anomaly",
        idempotency_key="idem_tok_999",
        target_type=ReplayTargetType.BATCH,
    )
    exec_res = await coordinator.execute(exec_cmd)
    assert exec_res.is_ok
    result_dto = exec_res.unwrap()
    assert result_dto.status == ReplayStatus.IN_FLIGHT
    assert result_dto.target_id == "bat_001"
    assert result_dto.target_type == ReplayTargetType.BATCH
    assert result_dto.replay_id.startswith("rpl_")
    assert result_dto.trace_id.startswith("trc_")

    assert len(raw_proc.replayed_targets) == 1
    t_id, tgt_id, new_trc, _ = raw_proc.replayed_targets[0]
    assert t_id == "utility_bescom"
    assert tgt_id == "bat_001"
    assert new_trc == result_dto.trace_id


@pytest.mark.asyncio
async def test_replay_coordinator_unsupported_stage_returns_error() -> None:
    coordinator = UniversalReplayCoordinator()

    # Request stage without registered processor
    req = ReplayPreviewRequestDTO(
        target_id="bat_999",
        tenant_id="tenant_x",
        target_stage=ReplayStage.STAGE_3_CANONICAL_MODEL,
    )
    res = await coordinator.preview(req)
    assert res.is_err
    assert isinstance(res.unwrap_err(), UnsupportedReplayStageError)


@pytest.mark.asyncio
async def test_replay_coordinator_failed_stage_execution() -> None:
    coordinator = UniversalReplayCoordinator()
    failing_proc = FakeDomainStageProcessor(
        ReplayStage.STAGE_2_STAGED_REPLICA, should_succeed=False
    )
    coordinator.register_processor(failing_proc)

    cmd = ExecuteReplayCommandDTO(
        target_id="bat_err",
        tenant_id="tenant_y",
        target_stage=ReplayStage.STAGE_2_STAGED_REPLICA,
        actor="user_123",
        reason="Testing failure path",
        idempotency_key="idem_err",
    )
    exec_res = await coordinator.execute(cmd)
    assert exec_res.is_err
    assert "Simulated pipeline failure" in str(exec_res.unwrap_err())
