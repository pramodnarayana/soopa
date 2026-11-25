"""IP Control Plane ConfigCatalogProviderPort serving Stitch and MappingSpec snapshots & deltas."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from database.config_changelog import get_latest_config_changelog_version_in_session
from ip.engine.adapters.outbound.database.models.control_plane import (
    MappingSpecRecord,
    StitchRecord,
)
from ip.engine.domain.enums import IP_CONFIG_APP_ID, IpConfigEntityType
from seedwork.domain.types import JsonDict, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_sync.domain.checksum import compute_payload_checksum, compute_snapshot_checksum
from config_sync.domain.dtos import ConfigDeltaEvent, ConfigEntityRecord, ConfigSnapshot
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _stitch_record_to_payload(record: StitchRecord) -> JsonDict:
    raw_filters = (
        dict(record.filter_conditions) if isinstance(record.filter_conditions, dict) else {}
    )
    idemp_field = str(raw_filters.pop("__idempotency_key_field__", "") or "")
    conc_field = str(raw_filters.pop("__concurrency_key_field__", "") or "")
    linked_id = str(raw_filters.pop("__linked_stitch_id__", "") or "") or None
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "canonical_event_type": record.canonical_event_type,
        "target_workflow_id": record.target_workflow_id,
        "name": record.name,
        "description": record.description,
        "mapping_spec_id": record.mapping_spec_id,
        "filter_conditions": raw_filters,
        "is_active": record.is_active,
        "idempotency_key_field": idemp_field,
        "concurrency_key_field": conc_field,
        "linked_stitch_id": linked_id,
    }


def _mapping_spec_record_to_payload(record: MappingSpecRecord) -> JsonDict:
    rules_value: list[JsonValue] = [dict(r) for r in record.rules]
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "name": record.name,
        "description": record.description,
        "source_type": record.source_type,
        "target_connection_id": record.target_connection_id,
        "target_entity_name": record.target_entity_name,
        "version": record.version,
        "rules": rules_value,
        "is_active": record.is_active,
    }


class IpConfigCatalogProvider(ConfigCatalogProviderPort):
    """Serves full tenant Stitch + MappingSpec snapshots and monotonic deltas over Dynamic Watch."""

    def __init__(
        self,
        *,
        session_factory: SessionScopeFactory,
        changelog_repo: ConfigChangelogRepositoryPort,
    ) -> None:
        self._session_scope = session_factory
        self._changelog_repo = changelog_repo

    @property
    def app_id(self) -> str:
        return IP_CONFIG_APP_ID

    async def get_tenant_snapshot(self, *, tenant_id: str) -> ConfigSnapshot:
        entities: list[ConfigEntityRecord] = []
        async with self._session_scope() as session:
            # Read version FIRST inside the same transaction so any concurrent commit V+1
            # during entity reads is guaranteed to be replayed as a live delta > version.
            version = await get_latest_config_changelog_version_in_session(
                session,
                app_id=IP_CONFIG_APP_ID,
                tenant_id=tenant_id,
                shared_tenant_ids=("*",),
            )
            stitch_rows = (
                (
                    await session.execute(
                        select(StitchRecord)
                        .where(StitchRecord.tenant_id.in_((tenant_id, "*")))
                        .order_by(StitchRecord.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            for row in stitch_rows:
                payload = _stitch_record_to_payload(row)
                entities.append(
                    ConfigEntityRecord(
                        entity_type=IpConfigEntityType.STITCH.value,
                        entity_id=row.id,
                        tenant_id=row.tenant_id,
                        payload=payload,
                        checksum=compute_payload_checksum(payload),
                    )
                )

            spec_rows = (
                (
                    await session.execute(
                        select(MappingSpecRecord)
                        .where(
                            MappingSpecRecord.tenant_id == tenant_id,
                            MappingSpecRecord.is_active.is_(True),
                        )
                        .order_by(MappingSpecRecord.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            for spec in spec_rows:
                payload = _mapping_spec_record_to_payload(spec)
                entities.append(
                    ConfigEntityRecord(
                        entity_type=IpConfigEntityType.MAPPING_SPEC.value,
                        entity_id=spec.id,
                        tenant_id=spec.tenant_id,
                        payload=payload,
                        checksum=compute_payload_checksum(payload),
                    )
                )

        frozen_entities = tuple(entities)
        return ConfigSnapshot(
            app_id=IP_CONFIG_APP_ID,
            tenant_id=tenant_id,
            version=version,
            entities=frozen_entities,
            checksum=compute_snapshot_checksum(frozen_entities),
        )

    async def get_deltas_since(
        self, *, tenant_id: str, since_version: int
    ) -> list[ConfigDeltaEvent]:
        return await self._changelog_repo.get_deltas_since(
            app_id=IP_CONFIG_APP_ID,
            tenant_id=tenant_id,
            since_version=since_version,
        )


__all__ = [
    "IP_CONFIG_APP_ID",
    "IpConfigCatalogProvider",
    "IpConfigEntityType",
]
