"""SQLAlchemy repository adapter for MappingSpec aggregates in the Control Plane (`ip.mapping_specs`)."""

from __future__ import annotations

from datetime import UTC, datetime

from config_sync.domain.checksum import compute_payload_checksum
from config_sync.domain.enums import ConfigChangeAction, ConfigSyncChannel
from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import MappingSpecRecord
from ip.engine.domain.config_payloads import mapping_spec_to_config_payload
from ip.engine.domain.enums import IP_CONFIG_APP_ID, IpConfigEntityType
from ip.engine.domain.mapping.enums import MappingRuleType
from ip.engine.domain.mapping.mapping_spec import MappingRule, MappingSpec
from ip.engine.ports.outbound.mapping_spec_repository_port import MappingSpecRepositoryPort
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.config_changelog import record_config_changelog_entry


class SqlAlchemyMappingSpecRepository(GlobalSqlAlchemyRepository, MappingSpecRepositoryPort):
    """PostgreSQL SQLAlchemy implementation of MappingSpecRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _rules_to_domain(raw_rules: list[JsonDict]) -> tuple[MappingRule, ...]:
        result: list[MappingRule] = []
        for r in raw_rules:
            rule_type_str = str(r.get("rule_type") or r.get("ruleType") or "DIRECT").upper()
            try:
                rule_type = MappingRuleType(rule_type_str)
            except ValueError:
                rule_type = MappingRuleType.DIRECT

            result.append(
                MappingRule(
                    target_field=str(r.get("target_field") or r.get("targetField") or ""),
                    rule_type=rule_type,
                    source_field=(
                        str(r["source_field"])
                        if "source_field" in r and r["source_field"] is not None
                        else str(r["sourceField"])
                        if "sourceField" in r and r["sourceField"] is not None
                        else None
                    ),
                    constant_value=r.get("constant_value", r.get("constantValue")),
                    expression=(
                        str(r["expression"])
                        if "expression" in r and r["expression"] is not None
                        else None
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _rules_to_orm(rules: tuple[MappingRule, ...]) -> list[JsonDict]:
        return [
            {
                "target_field": r.target_field,
                "rule_type": r.rule_type.value,
                "source_field": r.source_field,
                "constant_value": r.constant_value,
                "expression": r.expression,
            }
            for r in rules
        ]

    @staticmethod
    def _to_domain_model(record: MappingSpecRecord) -> MappingSpec:
        return MappingSpec(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            description=record.description,
            source_type=record.source_type,
            target_connection_id=record.target_connection_id,
            target_entity_name=record.target_entity_name,
            version=record.version,
            rules=SqlAlchemyMappingSpecRepository._rules_to_domain(record.rules),
            is_active=record.is_active,
        )

    @staticmethod
    def _to_orm_model(spec: MappingSpec, now: datetime) -> MappingSpecRecord:
        return MappingSpecRecord(
            id=spec.id,
            tenant_id=spec.tenant_id,
            name=spec.name,
            description=spec.description,
            source_type=spec.source_type,
            target_connection_id=spec.target_connection_id,
            target_entity_name=spec.target_entity_name,
            version=spec.version,
            rules=SqlAlchemyMappingSpecRepository._rules_to_orm(spec.rules),
            is_active=spec.is_active,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _update_record_from_domain(
        record: MappingSpecRecord,
        spec: MappingSpec,
        now: datetime,
    ) -> None:
        record.name = spec.name
        record.description = spec.description
        record.source_type = spec.source_type
        record.target_connection_id = spec.target_connection_id
        record.target_entity_name = spec.target_entity_name
        record.version = spec.version
        record.rules = SqlAlchemyMappingSpecRepository._rules_to_orm(spec.rules)
        record.is_active = spec.is_active
        record.updated_at = now

    async def save(self, spec: MappingSpec) -> None:
        now = datetime.now(UTC)
        stmt = select(MappingSpecRecord).where(
            MappingSpecRecord.id == spec.id,
            MappingSpecRecord.tenant_id == spec.tenant_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record is None:
            self.session.add(self._to_orm_model(spec, now))
        else:
            self._update_record_from_domain(record, spec, now)

        self._drain_events(spec, default_tenant_id=spec.tenant_id)
        payload = mapping_spec_to_config_payload(spec)
        await record_config_changelog_entry(
            self.session,
            event_id=generate_id(SystemIdPrefix.GENERIC),
            app_id=IP_CONFIG_APP_ID,
            tenant_id=spec.tenant_id,
            entity_type=IpConfigEntityType.MAPPING_SPEC.value,
            entity_id=spec.id,
            action=ConfigChangeAction.UPSERT.value,
            checksum=compute_payload_checksum(payload),
            payload=dict(payload),
            notify_channel=ConfigSyncChannel.CONFIG_CHANGELOG_NOTIFY.value,
        )

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> MappingSpec | None:
        stmt = select(MappingSpecRecord).where(
            MappingSpecRecord.id == mapping_spec_id,
            MappingSpecRecord.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return self._to_domain_model(record) if record is not None else None

    async def get_latest_by_target(
        self,
        *,
        tenant_id: str,
        target_connection_id: str,
        target_entity_name: str,
    ) -> MappingSpec | None:
        stmt = (
            select(MappingSpecRecord)
            .where(
                MappingSpecRecord.tenant_id == tenant_id,
                MappingSpecRecord.target_connection_id == target_connection_id,
                MappingSpecRecord.target_entity_name == target_entity_name,
                MappingSpecRecord.is_active.is_(True),
            )
            .order_by(desc(MappingSpecRecord.version))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        return self._to_domain_model(record) if record is not None else None

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        target_connection_id: str | None = None,
    ) -> list[MappingSpec]:
        stmt = select(MappingSpecRecord).where(MappingSpecRecord.tenant_id == tenant_id)
        if source_type:
            stmt = stmt.where(MappingSpecRecord.source_type == source_type)
        if target_connection_id:
            stmt = stmt.where(MappingSpecRecord.target_connection_id == target_connection_id)

        stmt = stmt.order_by(MappingSpecRecord.name.asc(), desc(MappingSpecRecord.version))
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def delete(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> None:
        """Deletes a MappingSpec record for a tenant and appends a DELETE changelog delta."""
        stmt = delete(MappingSpecRecord).where(
            MappingSpecRecord.id == mapping_spec_id,
            MappingSpecRecord.tenant_id == tenant_id,
        )
        await self.session.execute(stmt)
        tombstone: JsonDict = {"id": mapping_spec_id, "tenant_id": tenant_id}
        await record_config_changelog_entry(
            self.session,
            event_id=generate_id(SystemIdPrefix.GENERIC),
            app_id=IP_CONFIG_APP_ID,
            tenant_id=tenant_id,
            entity_type=IpConfigEntityType.MAPPING_SPEC.value,
            entity_id=mapping_spec_id,
            action=ConfigChangeAction.DELETE.value,
            checksum=compute_payload_checksum(tombstone),
            payload=dict(tombstone),
            notify_channel=ConfigSyncChannel.CONFIG_CHANGELOG_NOTIFY.value,
        )
