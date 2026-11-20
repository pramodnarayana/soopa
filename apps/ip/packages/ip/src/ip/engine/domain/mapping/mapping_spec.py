"""Domain model for declarative Field Mapping Specs connecting canonical models to wire contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.types import JsonDict, JsonValue

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.mapping.enums import MappingRuleType
from ip.engine.domain.mapping.events import MappingSpecDeletedEvent, MappingSpecSavedEvent


@dataclass(frozen=True, kw_only=True)
class MappingRule:
    """A single declarative translation rule from canonical field to destination wire field."""

    target_field: str
    rule_type: MappingRuleType = MappingRuleType.DIRECT
    source_field: str | None = None
    constant_value: JsonValue = None
    expression: str | None = None

    def apply(self, source_payload: JsonDict) -> tuple[bool, JsonValue]:
        """Applies this rule to a source payload. Returns (include_in_output, value)."""
        if self.rule_type == MappingRuleType.IGNORE:
            return False, None
        if self.rule_type == MappingRuleType.CONSTANT:
            return True, self.constant_value
        if self.rule_type == MappingRuleType.DIRECT:
            src_key = self.source_field or self.target_field
            return True, source_payload.get(src_key)
        if self.rule_type == MappingRuleType.EXPRESSION:
            src_key = self.source_field or self.target_field
            return True, source_payload.get(src_key)
        return False, None


@dataclass(kw_only=True)
class MappingSpec(AggregateRoot):
    """First-class domain aggregate defining declarative translation rules
    from a source canonical event type to a destination connection's target entity.
    """

    ID_PREFIX: ClassVar[str] = IpIdPrefix.MAPPING_SPEC.value

    id: str
    tenant_id: str
    name: str
    description: str = ""
    source_type: str
    target_connection_id: str
    target_entity_name: str
    version: int = 1
    rules: tuple[MappingRule, ...] = field(default_factory=tuple)
    is_active: bool = True

    def project(self, source_payload: JsonDict) -> JsonDict:
        """Projects a canonical payload into target wire contract format."""
        out: JsonDict = {}
        for rule in self.rules:
            include, value = rule.apply(source_payload)
            if include:
                out[rule.target_field] = value
        return out

    def record_saved(self) -> None:
        """Emits MappingSpecSavedEvent domain event."""
        self.add_domain_event(
            MappingSpecSavedEvent(
                mapping_spec_id=self.id,
                tenant_id=self.tenant_id,
                name=self.name,
                source_type=self.source_type,
                target_connection_id=self.target_connection_id,
                target_entity_name=self.target_entity_name,
                version=self.version,
                is_active=self.is_active,
            )
        )

    def mark_deleted(self) -> None:
        """Emits MappingSpecDeletedEvent domain event."""
        self.add_domain_event(
            MappingSpecDeletedEvent(
                mapping_spec_id=self.id,
                tenant_id=self.tenant_id,
                name=self.name,
            )
        )

    def activate(self) -> None:
        """Activates this mapping specification."""
        self.is_active = True
        self.record_saved()

    def deactivate(self) -> None:
        """Deactivates this mapping specification."""
        self.is_active = False
        self.record_saved()

    def update_spec(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        rules: tuple[MappingRule, ...] | None = None,
        is_active: bool | None = None,
    ) -> None:
        """Updates metadata, rules, or state on this mapping specification."""
        if name is not None:
            self.name = name.strip()
        if description is not None:
            self.description = description.strip()
        if rules is not None:
            self.rules = rules
        if is_active is not None:
            self.is_active = is_active
        self.record_saved()
