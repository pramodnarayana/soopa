"""QueryReplicaStepHandler adapter querying L2 Replica records."""

from __future__ import annotations

from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps.query_replica_steps import (
    QueryReplicaStepInput,
    QueryReplicaStepOutput,
)
from ip.engine.ports.outbound.replica_lookup_port import ReplicaLookupPort
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result
from orchestration.domain.failures import StepFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext, StepHandlerPort
from seedwork.domain.types import JsonDict


class QueryReplicaStepHandler(StepHandlerPort[JsonDict, JsonDict]):
    """Queries an L2 ReplicaRecord inside a Stitch workflow step (`EffectPolicy.PURE`)."""

    def __init__(
        self,
        replica_lookup: ReplicaLookupPort,
    ) -> None:
        self._replica_lookup = replica_lookup

    @property
    def step_type(self) -> str:
        return StitchStepType.QUERY_REPLICA.value

    @property
    def effect_policy(self) -> EffectPolicy:
        return EffectPolicy.PURE

    async def execute(
        self, context: StepContext, step_input: JsonDict
    ) -> Result[JsonDict, StepFailure]:
        parsed_res = QueryReplicaStepInput.from_payload(step_input)
        if parsed_res.is_err:
            return Result.err(
                TerminalFailure(
                    code=StepFailureCode.VALIDATION_REJECTED,
                    detail=parsed_res.unwrap_err().message,
                )
            )
        req = parsed_res.unwrap()

        rec = await self._replica_lookup.get_by_key(
            tenant_id=context.tenant_id,
            connection_id=req.connection_id,
            stream=req.stream,
            record_key=req.record_key,
        )
        if rec is None:
            return Result.ok(QueryReplicaStepOutput(found=False).to_payload())

        return Result.ok(
            QueryReplicaStepOutput(
                found=True,
                record_id=rec.id,
                version=rec.version,
                data=rec.data,
            ).to_payload()
        )


__all__ = ["QueryReplicaStepHandler"]
