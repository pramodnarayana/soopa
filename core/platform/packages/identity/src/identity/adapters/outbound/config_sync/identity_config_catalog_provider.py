"""Identity Control Plane ConfigCatalogProviderPort (Strictly Low-Cardinality Global Catalog).

Cardinality-Split Invariant (10/10 Gold Standard):
  - Serves ONLY the tiny global IAM metadata (< 1 MB RAM across 10M+ users):
    `trusted_issuers`, `email_domain_routes`, `capabilities`, platform-wide `roles`,
    and platform-wide `policy_rules`.
  - NEVER snapshots high-cardinality tables (`identity.users`, `identity.tenants`,
    `identity.tenant_users`, `identity.user_roles`, `identity.resource_grants`).
  - High-cardinality changes flow purely as tiny invalidation tombstones over
    `get_deltas_since` -> `IdentityInvalidationSink`.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from config_sync.domain.checksum import compute_payload_checksum, compute_snapshot_checksum
from config_sync.domain.dtos import (
    ConfigCursor,
    ConfigDeltaEvent,
    ConfigEntityRecord,
    ConfigSnapshot,
)
from config_sync.ports.config_catalog_provider_port import ConfigCatalogProviderPort
from config_sync.ports.config_changelog_port import ConfigChangelogRepositoryPort
from database.config_changelog import (
    ensure_repeatable_read_snapshot,
    get_latest_config_changelog_cursor_in_session,
)
from database.models.identity import (
    Capability as OrmCapability,
)
from database.models.identity import (
    EmailDomainRoute as OrmEmailDomainRoute,
)
from database.models.identity import (
    PolicyRule as OrmPolicyRule,
)
from database.models.identity import (
    Role as OrmRole,
)
from database.models.identity import (
    TrustedIssuer as OrmTrustedIssuer,
)
from seedwork.domain.types import JsonDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.constants import IDENTITY_CONFIG_APP_ID, IdentityConfigEntityType
from identity.domain.identity_context import PLATFORM_TENANT_ID

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class IdentityConfigCatalogProvider(ConfigCatalogProviderPort):
    """Serves low-cardinality global IAM snapshots and cache-invalidation deltas over Dynamic Watch."""

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
        return IDENTITY_CONFIG_APP_ID

    async def get_tenant_snapshot(self, *, tenant_id: str) -> ConfigSnapshot:
        entities: list[ConfigEntityRecord] = []
        async with self._session_scope() as session:
            await ensure_repeatable_read_snapshot(session)
            txid, version = await get_latest_config_changelog_cursor_in_session(
                session,
                app_id=IDENTITY_CONFIG_APP_ID,
                tenant_id=tenant_id,
                shared_tenant_ids=(PLATFORM_TENANT_ID,),
            )
            entities.extend(await self._load_trusted_issuers(session))
            entities.extend(await self._load_email_domain_routes(session))
            entities.extend(await self._load_capabilities(session))
            entities.extend(await self._load_platform_roles(session))
            entities.extend(await self._load_platform_policy_rules(session))

        frozen_entities = tuple(entities)
        return ConfigSnapshot(
            app_id=IDENTITY_CONFIG_APP_ID,
            tenant_id=tenant_id,
            version=version,
            txid=txid,
            entities=frozen_entities,
            checksum=compute_snapshot_checksum(frozen_entities),
        )

    async def get_deltas_since(
        self, *, tenant_id: str, since_cursor: ConfigCursor
    ) -> list[ConfigDeltaEvent]:
        return await self._changelog_repo.get_deltas_since(
            app_id=IDENTITY_CONFIG_APP_ID,
            tenant_id=tenant_id,
            since_cursor=since_cursor,
        )

    @staticmethod
    async def _load_trusted_issuers(session: AsyncSession) -> list[ConfigEntityRecord]:
        stmt = (
            select(OrmTrustedIssuer)
            .where(OrmTrustedIssuer.is_active.is_(True))
            .order_by(OrmTrustedIssuer.issuer.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        records: list[ConfigEntityRecord] = []
        for row in rows:
            payload: JsonDict = {
                "issuer": row.issuer,
                "jwks_uri": row.jwks_uri,
                "allowed_audiences": list(row.allowed_audiences or []),
                "jwks_host_header": row.jwks_host_header,
                "is_active": row.is_active,
            }
            records.append(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.TRUSTED_ISSUER.value,
                    entity_id=row.issuer,
                    tenant_id=PLATFORM_TENANT_ID,
                    payload=payload,
                    checksum=compute_payload_checksum(payload),
                )
            )
        return records

    @staticmethod
    async def _load_email_domain_routes(session: AsyncSession) -> list[ConfigEntityRecord]:
        stmt = select(OrmEmailDomainRoute).order_by(OrmEmailDomainRoute.domain.asc())
        rows = (await session.execute(stmt)).scalars().all()
        records: list[ConfigEntityRecord] = []
        for row in rows:
            payload: JsonDict = {
                "domain": row.domain,
                "tenant_id": row.tenant_id,
                "idp_issuer": row.idp_issuer,
                "idp_realm_name": row.idp_realm_name,
                "sso_enforced": row.sso_enforced,
                "verified_at": row.verified_at.isoformat() if row.verified_at else None,
            }
            records.append(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.EMAIL_DOMAIN_ROUTE.value,
                    entity_id=row.domain,
                    tenant_id=PLATFORM_TENANT_ID,
                    payload=payload,
                    checksum=compute_payload_checksum(payload),
                )
            )
        return records

    @staticmethod
    async def _load_capabilities(session: AsyncSession) -> list[ConfigEntityRecord]:
        stmt = select(OrmCapability).order_by(OrmCapability.code.asc())
        rows = (await session.execute(stmt)).scalars().all()
        records: list[ConfigEntityRecord] = []
        for row in rows:
            payload: JsonDict = {
                "code": row.code,
                "domain": row.domain,
                "resource": row.resource,
                "action": row.action,
                "display_name": row.display_name,
                "description": row.description,
                "is_sensitive": row.is_sensitive,
                "requires_mfa": row.requires_mfa,
                "machine_allowed": row.machine_allowed,
                "tier_scope": row.tier_scope,
            }
            records.append(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.CAPABILITY.value,
                    entity_id=row.code,
                    tenant_id=PLATFORM_TENANT_ID,
                    payload=payload,
                    checksum=compute_payload_checksum(payload),
                )
            )
        return records

    @staticmethod
    async def _load_platform_roles(session: AsyncSession) -> list[ConfigEntityRecord]:
        stmt = (
            select(OrmRole)
            .where(OrmRole.tenant_id == PLATFORM_TENANT_ID, OrmRole.deleted_at.is_(None))
            .order_by(OrmRole.id.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        records: list[ConfigEntityRecord] = []
        for row in rows:
            payload: JsonDict = {
                "id": row.id,
                "tenant_id": row.tenant_id or PLATFORM_TENANT_ID,
                "name": row.name,
                "capabilities": list(row.capabilities or []),
                "deny_capabilities": list(row.deny_capabilities or []),
                "is_system": row.is_system,
            }
            records.append(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.PLATFORM_ROLE.value,
                    entity_id=row.id,
                    tenant_id=PLATFORM_TENANT_ID,
                    payload=payload,
                    checksum=compute_payload_checksum(payload),
                )
            )
        return records

    @staticmethod
    async def _load_platform_policy_rules(session: AsyncSession) -> list[ConfigEntityRecord]:
        stmt = (
            select(OrmPolicyRule)
            .where(
                OrmPolicyRule.tenant_id == PLATFORM_TENANT_ID,
                OrmPolicyRule.is_active.is_(True),
            )
            .order_by(OrmPolicyRule.priority.asc(), OrmPolicyRule.id.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()
        records: list[ConfigEntityRecord] = []
        for row in rows:
            payload: JsonDict = {
                "id": row.id,
                "tenant_id": row.tenant_id,
                "engine_type": row.engine_type,
                "effect": row.effect,
                "subject_expr": row.subject_expr,
                "resource_type": row.resource_type,
                "action_pattern": row.action_pattern,
                "condition_json": dict(row.condition_json or {}),
                "priority": row.priority,
                "is_active": row.is_active,
            }
            records.append(
                ConfigEntityRecord(
                    entity_type=IdentityConfigEntityType.POLICY_RULE.value,
                    entity_id=row.id,
                    tenant_id=PLATFORM_TENANT_ID,
                    payload=payload,
                    checksum=compute_payload_checksum(payload),
                )
            )
        return records


__all__ = ["IDENTITY_CONFIG_APP_ID", "IdentityConfigCatalogProvider"]
