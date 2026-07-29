import logging
from contextlib import aclosing, asynccontextmanager
from typing import Any

from database.connection import DatabaseRouter
from database.models.control_plane import AS2Partner as GlobalAS2Partner
from database.models.control_plane import AS2Partnership as GlobalAS2Partnership
from database.models.control_plane import InboundRoute as GlobalInboundRoute
from database.models.control_plane import OutboundEdiHeader as GlobalOutboundEdiHeader
from database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from database.models.control_plane import SFTPPartner as GlobalSFTPPartner
from database.models.control_plane import Webhook as GlobalWebhook
from database.models.data_plane import AS2Partner as TenantAS2Partner
from database.models.data_plane import AS2Partnership as TenantAS2Partnership
from database.models.data_plane import InboundRoute as TenantInboundRoute
from database.models.data_plane import OutboundEdiHeader as TenantOutboundEdiHeader
from database.models.data_plane import OutboundRoute as TenantOutboundRoute
from database.models.data_plane import SFTPPartner as TenantSFTPPartner
from database.models.data_plane import Webhook as TenantWebhook
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
from worker.ports.replication import ReplicationPort
from worker.ports.tenant import TenantPort

logger = logging.getLogger(__name__)


class SqlAlchemyReplicationAdapter(ReplicationPort):
    def __init__(self, db_router: DatabaseRouter, tenant_port: TenantPort):
        self.db_router = db_router
        self.tenant_port = tenant_port

    @asynccontextmanager
    async def _get_sessions(self, tenant_id: str) -> Any:
        try:
            shard_name, shard_dsn = await self.tenant_port.resolve_shard(tenant_id)
        except Exception as e:
            raise PermanentProvisioningError(f"Tenant {tenant_id} unresolvable: {e}") from e

        global_gen = self.db_router.get_global_session()
        tenant_gen = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)

        async with aclosing(global_gen) as global_gen_ctx, aclosing(tenant_gen) as tenant_gen_ctx:
            global_session = await global_gen_ctx.__anext__()
            tenant_session = await tenant_gen_ctx.__anext__()
            yield global_session, tenant_session

    async def replicate_tenant_configuration(self, tenant_id: str) -> None:
        """Full tenant state sync. Retained only for global broadcasts (PROVISION_ALL_TENANTS)."""
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                await self._do_replicate(tenant_id, global_session, tenant_session)
                await tenant_session.commit()
                logger.info(f"Successfully replicated configuration for tenant_id={tenant_id}")
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate tenant {tenant_id}: {e}"
                ) from e

    async def _do_replicate(self, tenant_id: str, global_session: Any, tenant_session: Any) -> None:
        # Re-use granular methods for the full sync

        # AS2 Partners
        tp_result = await global_session.execute(
            select(GlobalAS2Partner).where(
                (GlobalAS2Partner.tenant_id == tenant_id) | (GlobalAS2Partner.tenant_id.is_(None))
            )
        )
        for tp in tp_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, tp, TenantAS2Partner)

        # AS2 Partnerships
        ps_result = await global_session.execute(
            select(GlobalAS2Partnership).where(
                (GlobalAS2Partnership.tenant_id == tenant_id)
                | (GlobalAS2Partnership.tenant_id.is_(None))
            )
        )
        for ps in ps_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, ps, TenantAS2Partnership)

        # SFTP Partners
        sftp_result = await global_session.execute(
            select(GlobalSFTPPartner).where(GlobalSFTPPartner.tenant_id == tenant_id)
        )
        for sftp in sftp_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, sftp, TenantSFTPPartner)

        # Webhooks
        wh_result = await global_session.execute(
            select(GlobalWebhook).where(GlobalWebhook.tenant_id == tenant_id)
        )
        for wh in wh_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, wh, TenantWebhook)

        # Inbound Routes
        ir_result = await global_session.execute(
            select(GlobalInboundRoute).where(GlobalInboundRoute.tenant_id == tenant_id)
        )
        for ir in ir_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, ir, TenantInboundRoute)

        # Outbound Routes
        or_result = await global_session.execute(
            select(GlobalOutboundRoute).where(GlobalOutboundRoute.tenant_id == tenant_id)
        )
        for route in or_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, route, TenantOutboundRoute)

        # Outbound EDI Headers
        oeh_result = await global_session.execute(
            select(GlobalOutboundEdiHeader).where(GlobalOutboundEdiHeader.tenant_id == tenant_id)
        )
        for oeh in oeh_result.scalars().all():
            await self._upsert_entity(tenant_session, tenant_id, oeh, TenantOutboundEdiHeader)

        # Sync deletes
        await self._sync_deletes(
            tenant_id,
            global_session,
            tenant_session,
            GlobalOutboundEdiHeader,
            TenantOutboundEdiHeader,
            False,
        )
        await self._sync_deletes(
            tenant_id,
            global_session,
            tenant_session,
            GlobalOutboundRoute,
            TenantOutboundRoute,
            False,
        )
        await self._sync_deletes(
            tenant_id, global_session, tenant_session, GlobalInboundRoute, TenantInboundRoute, False
        )
        await self._sync_deletes(
            tenant_id, global_session, tenant_session, GlobalWebhook, TenantWebhook, False
        )
        await self._sync_deletes(
            tenant_id, global_session, tenant_session, GlobalSFTPPartner, TenantSFTPPartner, False
        )
        await self._sync_deletes(
            tenant_id,
            global_session,
            tenant_session,
            GlobalAS2Partnership,
            TenantAS2Partnership,
            True,
        )
        await self._sync_deletes(
            tenant_id, global_session, tenant_session, GlobalAS2Partner, TenantAS2Partner, True
        )

    # --- Granular Upsert / Delete Methods ---

    async def replicate_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalAS2Partner).where(GlobalAS2Partner.id == partner_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(tenant_session, tenant_id, entity, TenantAS2Partner)
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate AS2Partner {partner_id}: {e}"
                ) from e

    async def delete_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._granular_delete(tenant_id, partner_id, TenantAS2Partner)

    async def replicate_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalAS2Partnership).where(GlobalAS2Partnership.id == partnership_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(
                        tenant_session, tenant_id, entity, TenantAS2Partnership
                    )
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate AS2Partnership {partnership_id}: {e}"
                ) from e

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        await self._granular_delete(tenant_id, partnership_id, TenantAS2Partnership)

    async def replicate_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalSFTPPartner).where(GlobalSFTPPartner.id == partner_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(tenant_session, tenant_id, entity, TenantSFTPPartner)
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate SFTPPartner {partner_id}: {e}"
                ) from e

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        await self._granular_delete(tenant_id, partner_id, TenantSFTPPartner)

    async def replicate_webhook(self, tenant_id: str, webhook_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalWebhook).where(GlobalWebhook.id == webhook_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(tenant_session, tenant_id, entity, TenantWebhook)
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate Webhook {webhook_id}: {e}"
                ) from e

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        await self._granular_delete(tenant_id, webhook_id, TenantWebhook)

    async def replicate_inbound_route(self, tenant_id: str, route_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalInboundRoute).where(GlobalInboundRoute.id == route_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(tenant_session, tenant_id, entity, TenantInboundRoute)
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate InboundRoute {route_id}: {e}"
                ) from e

    async def delete_inbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._granular_delete(tenant_id, route_id, TenantInboundRoute)

    async def replicate_outbound_route(self, tenant_id: str, route_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalOutboundRoute).where(GlobalOutboundRoute.id == route_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(
                        tenant_session, tenant_id, entity, TenantOutboundRoute
                    )
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate OutboundRoute {route_id}: {e}"
                ) from e

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> None:
        await self._granular_delete(tenant_id, route_id, TenantOutboundRoute)

    async def replicate_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                res = await global_session.execute(
                    select(GlobalOutboundEdiHeader).where(GlobalOutboundEdiHeader.id == header_id)
                )
                entity = res.scalars().first()
                if entity:
                    await self._upsert_entity(
                        tenant_session, tenant_id, entity, TenantOutboundEdiHeader
                    )
                    await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate OutboundEdiHeader {header_id}: {e}"
                ) from e

    async def delete_outbound_edi_header(self, tenant_id: str, header_id: str) -> None:
        await self._granular_delete(tenant_id, header_id, TenantOutboundEdiHeader)

    async def _upsert_entity(
        self, tenant_session: AsyncSession, tenant_id: str, global_entity: Any, tenant_model: Any
    ) -> None:
        data = {
            col.name: getattr(global_entity, col.name)
            for col in global_entity.__table__.columns
            if hasattr(global_entity, col.name)
        }
        data["tenant_id"] = tenant_id

        stmt = insert(tenant_model).values(**data)
        update_data = {k: v for k, v in data.items() if k != "id"}

        stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=update_data)
        await tenant_session.execute(stmt)

    async def _granular_delete(self, tenant_id: str, entity_id: str, tenant_model: Any) -> None:
        async with self._get_sessions(tenant_id) as (global_session, tenant_session):
            try:
                await tenant_session.execute(
                    delete(tenant_model).where(tenant_model.id == entity_id)
                )
                await tenant_session.commit()
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to delete {tenant_model.__name__} {entity_id}: {e}"
                ) from e

    async def _sync_deletes(
        self,
        tenant_id: str,
        global_session: Any,
        tenant_session: Any,
        global_model: Any,
        tenant_model: Any,
        include_shared: bool,
    ) -> None:
        # Get all valid IDs from global
        global_stmt = select(global_model.id).where(global_model.tenant_id == tenant_id)
        if include_shared:
            global_stmt = select(global_model.id).where(
                (global_model.tenant_id == tenant_id) | (global_model.tenant_id.is_(None))
            )
        global_ids_result = await global_session.execute(global_stmt)
        global_ids = set(global_ids_result.scalars().all())

        # Get all IDs in tenant db
        tenant_stmt = select(tenant_model.id).where(tenant_model.tenant_id == tenant_id)
        tenant_ids_result = await tenant_session.execute(tenant_stmt)
        tenant_ids = set(tenant_ids_result.scalars().all())

        # Delete ids in tenant that are not in global
        ids_to_delete = tenant_ids - global_ids
        if ids_to_delete:
            logger.info(
                f"[tenant={tenant_id}] Deleting {len(ids_to_delete)} stale {tenant_model.__tablename__} record(s)"
            )
            await tenant_session.execute(
                delete(tenant_model).where(tenant_model.id.in_(list(ids_to_delete)))
            )
