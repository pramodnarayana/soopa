"""EDI Canonical JSON Transaction Aggregate Root."""

from __future__ import annotations

from dataclasses import dataclass, replace

from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.record_base import EdiRecordBase
from edi.domain.types import JsonDict, JsonValue

__all__ = ["EdiJson"]


@dataclass(kw_only=True)
class EdiJson(EdiRecordBase):
    trading_partner_id: str | None = None
    transaction_type: str | None = None
    standard: str | None = None
    business_metadata: JsonDict | None = None
    payload: JsonValue | None = None
    storage_uri: str | None = None

    def _sanitized_metadata_copy(self) -> JsonDict | None:
        if self.business_metadata is None:
            return None
        metadata = dict(self.business_metadata)
        metadata.pop("_idempotency_key", None)
        return metadata

    def clone_for_transform_retry(self, new_id: str, new_trace_id: str) -> EdiJson:
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.RECEIVED,
            error_code=None,
            error_details=None,
            status_message=None,
            business_metadata=self._sanitized_metadata_copy(),
        )
        cloned.clear_domain_events()
        cloned.clear_trace_events()
        return cloned

    def clone_for_delivery_retry(self, new_id: str, new_trace_id: str) -> EdiJson:
        cloned = replace(
            self,
            id=new_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=self.original_trace_id or self.trace_id,
            replay_count=self.replay_count + 1,
            status=MessageStatus.PENDING_DELIVERY,
            error_code=None,
            error_details=None,
            status_message=None,
            business_metadata=self._sanitized_metadata_copy(),
        )
        cloned.clear_domain_events()
        cloned.clear_trace_events()
        return cloned

    def clone_with_modified_payload(
        self,
        *,
        new_id: str,
        new_trace_id: str,
        parsed_payload: JsonValue,
        actor: str,
    ) -> EdiJson:
        """Clone with operator-corrected JSON payload and record audit traces on both records."""
        root_trace_id = self.original_trace_id or self.trace_id
        is_outbound = self.direction == EdiDirection.OUTBOUND
        new_json = EdiJson(
            id=new_id,
            tenant_id=self.tenant_id,
            trace_id=new_trace_id,
            parent_trace_id=self.trace_id,
            original_trace_id=root_trace_id,
            direction=self.direction,
            status=MessageStatus.RECEIVED if is_outbound else MessageStatus.TRANSFORMED,
            trading_partner_id=self.trading_partner_id,
            transaction_type=self.transaction_type,
            standard=self.standard,
            business_metadata=self._sanitized_metadata_copy(),
            payload=parsed_payload,
        )

        if is_outbound:
            new_json.request_transformation(
                trading_partner_id=new_json.trading_partner_id,
            )
            audit_type = EdiTraceEventType.MODIFY_AND_REPLAY_TRANSFORM
        else:
            new_json.request_delivery(
                trading_partner_id=new_json.trading_partner_id,
                transaction_type=new_json.transaction_type,
            )
            audit_type = EdiTraceEventType.MODIFY_AND_REPLAY_DELIVER

        self.record_modified_and_replayed(
            new_trace_id=new_trace_id,
            event_type=audit_type,
            actor=actor,
        )
        new_json.record_created_from_modification(
            parent_trace_id=self.trace_id,
            original_trace_id=root_trace_id,
            actor=actor,
        )
        return new_json
