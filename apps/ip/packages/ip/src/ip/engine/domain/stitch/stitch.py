"""Domain aggregate root for the IP Layer-4 Stitch Engine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict, JsonPrimitive

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.stitch.events import (
    StitchDeletedEvent,
    StitchRegisteredEvent,
    StitchUpdatedEvent,
)


@dataclass(kw_only=True)
class Stitch(AggregateRoot):
    """Pure Event Subscription aggregate root.

    Binds an L3 Canonical Event type and optional tenant filter predicates
    to an automated downstream Workflow.
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.STITCH.value

    id: str
    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str = ""
    workflow_id: str = ""
    workflow_version: int = 1
    name: str = ""
    description: str = ""
    mapping_spec_id: str | None = None
    filter_conditions: Mapping[str, JsonPrimitive] = field(default_factory=dict)
    is_active: bool = True
    is_trigger: bool = True
    idempotency_key_field: str = ""
    concurrency_key_field: str = ""
    linked_stitch_id: str | None = None
    correlation_key_field: str = ""

    def __post_init__(self) -> None:
        if not self.target_workflow_id and self.workflow_id:
            self.target_workflow_id = self.workflow_id
        elif not self.workflow_id and self.target_workflow_id:
            self.workflow_id = self.target_workflow_id

    def matches_payload(self, payload: JsonDict) -> bool:
        """Evaluates declarative equality predicates against the canonical event payload."""
        if not self.filter_conditions:
            return True
        for key, expected in self.filter_conditions.items():
            if key.startswith("__"):
                continue
            actual = payload.get(key)
            if isinstance(expected, bool):
                if not isinstance(actual, bool) or actual != expected:
                    return False
            elif isinstance(expected, (int, float)):
                if isinstance(actual, bool) or actual != expected:
                    return False
            elif actual != expected:
                return False
        return True

    def extract_idempotency_key(self, payload: JsonDict, fallback_event_id: str) -> str:
        """Extracts the idempotency key using the configured field or falls back to event_id."""
        if self.idempotency_key_field:
            raw_val = payload.get(self.idempotency_key_field)
            if raw_val is not None and str(raw_val).strip():
                return f"{self.target_workflow_id}:{raw_val}"
        return f"{self.target_workflow_id}:{fallback_event_id}"

    def extract_concurrency_key(self, payload: JsonDict) -> str | None:
        """Extracts the concurrency key using the configured field if present."""
        if self.concurrency_key_field:
            raw_val = payload.get(self.concurrency_key_field)
            if raw_val is not None and str(raw_val).strip():
                return str(raw_val)
        return None

    def record_registered(self) -> None:
        """Records a StitchRegisteredEvent domain event on this aggregate."""
        self.add_domain_event(
            StitchRegisteredEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                canonical_event_type=self.canonical_event_type,
                target_workflow_id=self.target_workflow_id,
                is_active=self.is_active,
            )
        )

    def activate(self) -> None:
        """Activates this Stitch pipeline trigger."""
        self.is_active = True
        self.add_domain_event(
            StitchUpdatedEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                canonical_event_type=self.canonical_event_type,
                target_workflow_id=self.target_workflow_id,
                is_active=self.is_active,
            )
        )

    def deactivate(self) -> None:
        """Pauses or deactivates this Stitch pipeline trigger."""
        self.is_active = False
        self.add_domain_event(
            StitchUpdatedEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                canonical_event_type=self.canonical_event_type,
                target_workflow_id=self.target_workflow_id,
                is_active=self.is_active,
            )
        )

    def mark_deleted(self) -> None:
        """Records a StitchDeletedEvent domain event on this aggregate."""
        self.add_domain_event(
            StitchDeletedEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                target_workflow_id=self.target_workflow_id,
            )
        )

    def update_metadata(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        mapping_spec_id: str | None = None,
        filter_conditions: Mapping[str, JsonPrimitive] | None = None,
        is_active: bool | None = None,
    ) -> None:
        """Updates pipeline metadata, linked mapping spec, predicates, or active state."""
        if name is not None:
            self.name = name.strip()
        if description is not None:
            self.description = description.strip()
        if mapping_spec_id is not None:
            clean_spec_id = mapping_spec_id.strip() if mapping_spec_id else None
            self.mapping_spec_id = clean_spec_id or None
        if filter_conditions is not None:
            self.filter_conditions = filter_conditions
        if is_active is not None:
            self.is_active = is_active

        self.add_domain_event(
            StitchUpdatedEvent(
                stitch_id=self.id,
                tenant_id=self.tenant_id,
                canonical_event_type=self.canonical_event_type,
                target_workflow_id=self.target_workflow_id,
                is_active=self.is_active,
            )
        )


__all__ = ["Stitch"]
