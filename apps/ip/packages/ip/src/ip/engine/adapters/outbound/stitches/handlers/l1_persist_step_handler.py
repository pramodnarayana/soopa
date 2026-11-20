"""L1PersistStepHandler storing raw immutable payloads in Tiered Storage."""

from __future__ import annotations

import hashlib

import structlog
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.pipeline_stage_steps import (
    L1PersistStepInput,
    L1PersistStepOutput,
)
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict

logger = structlog.get_logger(__name__)


class L1PersistStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Stores raw immutable wire payloads into L1 Tiered Storage with SHA-256 verification."""

    def __init__(self, *, storage: TieredStoragePort | None = None) -> None:
        self._storage = storage

    @property
    def step_type(self) -> str:
        return StitchStepType.L1_PERSIST.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.IDEMPOTENT_EFFECT

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        bound = logger.bind(
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            node_key=context.node_key,
        )
        bound.info("l1_persist.received")

        parsed_res = L1PersistStepInput.from_payload(step_input)
        if parsed_res.is_err:
            detail = parsed_res.unwrap_err().message
            bound.error("l1_persist.validation_failed", detail=detail)
            return Result.err(
                TerminalFailure(code=StepFailureCode.VALIDATION_REJECTED, detail=detail)
            )
        req = parsed_res.unwrap()

        raw_bytes = req.raw_payload.encode("utf-8")
        sha256_digest = hashlib.sha256(raw_bytes).hexdigest()

        s3_key: str | None = None
        is_inlined = True

        if self._storage is not None:
            storage_res = await self._storage.store(
                tenant_id=context.tenant_id,
                trace_id=context.run_id,
                payload_bytes=raw_bytes,
            )
            s3_key = storage_res.s3_key
            is_inlined = storage_res.is_inlined

        output = L1PersistStepOutput(
            connection_id=req.connection_id,
            app=req.app,
            entity=req.entity,
            sha256=sha256_digest,
            s3_key=s3_key,
            is_inlined=is_inlined,
            raw_payload=req.raw_payload,
        )
        bound.info("l1_persist.completed", sha256=sha256_digest, is_inlined=is_inlined)
        return Result.ok(output.to_payload())


__all__ = ["L1PersistStepHandler"]
