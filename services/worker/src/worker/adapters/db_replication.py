import logging
from typing import Any

from database.connection import DatabaseRouter
from database.models.control_plane import AS2Partner as GlobalAS2Partner
from database.models.control_plane import AS2Partnership as GlobalAS2Partnership
from database.models.control_plane import InboundRoute as GlobalInboundRoute
from database.models.control_plane import OutboundRoute as GlobalOutboundRoute
from database.models.control_plane import SFTPPartner as GlobalSFTPPartner
from database.models.control_plane import Webhook as GlobalWebhook
from database.models.data_plane import AS2Partner as TenantAS2Partner
from database.models.data_plane import AS2Partnership as TenantAS2Partnership
from database.models.data_plane import InboundRoute as TenantInboundRoute
from database.models.data_plane import OutboundRoute as TenantOutboundRoute
from database.models.data_plane import SFTPPartner as TenantSFTPPartner
from database.models.data_plane import Webhook as TenantWebhook
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from worker.core.errors import PermanentProvisioningError, TransientProvisioningError
from worker.ports.replication import ReplicationPort
from worker.ports.tenant import TenantPort

logger = logging.getLogger(__name__)


class SqlAlchemyReplicationAdapter(ReplicationPort):
    def __init__(self, db_router: DatabaseRouter, tenant_port: TenantPort):
        self.db_router = db_router
        self.tenant_port = tenant_port

    async def replicate_tenant_configuration(self, tenant_id: int) -> None:
        """Copy all relevant configuration from Global DB to Tenant DB Shard."""

        try:
            shard_name, shard_dsn = await self.tenant_port.resolve_shard(tenant_id)
        except Exception as e:
            raise PermanentProvisioningError(f"Tenant {tenant_id} unresolvable: {e}") from e

        global_gen = self.db_router.get_global_session()
        tenant_gen = self.db_router.get_tenant_session(tenant_id, shard_name, shard_dsn)

        from contextlib import aclosing

        async with aclosing(global_gen) as global_gen_ctx, aclosing(tenant_gen) as tenant_gen_ctx:
            global_session = await global_gen_ctx.__anext__()
            tenant_session = await tenant_gen_ctx.__anext__()

            try:
                await self._do_replicate(tenant_id, global_session, tenant_session)
                await tenant_session.commit()
                logger.info(f"Successfully replicated configuration for tenant_id={tenant_id}")
            except Exception as e:
                await tenant_session.rollback()
                raise TransientProvisioningError(
                    f"Failed to replicate tenant {tenant_id}: {e}"
                ) from e

    async def _do_replicate(self, tenant_id: int, global_session: Any, tenant_session: Any) -> None:
        # --- AS2 Partners ---
        stmt = select(GlobalAS2Partner).where(
            (GlobalAS2Partner.tenant_id == tenant_id) | (GlobalAS2Partner.tenant_id == 0)
        )
        tp_result = await global_session.execute(stmt)
        as2_partners = tp_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(as2_partners)} AS2 partner(s)")

        for global_tp in as2_partners:
            logger.debug(
                f"[tenant={tenant_id}] Upserting AS2Partner id={global_tp.id} as2_id={global_tp.as2_id!r}"
            )
            insert_stmt = (
                insert(TenantAS2Partner)
                .values(
                    id=global_tp.id,
                    tenant_id=tenant_id,
                    name=global_tp.name,
                    as2_id=global_tp.as2_id,
                    public_cert_pem=global_tp.public_cert_pem,
                    public_cert_vault_ref=global_tp.public_cert_vault_ref,
                    private_key_vault_ref=global_tp.private_key_vault_ref,
                    prev_public_cert_pem=global_tp.prev_public_cert_pem,
                    prev_public_cert_vault_ref=global_tp.prev_public_cert_vault_ref,
                    prev_private_key_vault_ref=global_tp.prev_private_key_vault_ref,
                    url=global_tp.url,
                    active=global_tp.active,
                    created_at=global_tp.created_at,
                    updated_at=global_tp.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "tenant_id": tenant_id,
                        "name": global_tp.name,
                        "as2_id": global_tp.as2_id,
                        "public_cert_pem": global_tp.public_cert_pem,
                        "public_cert_vault_ref": global_tp.public_cert_vault_ref,
                        "private_key_vault_ref": global_tp.private_key_vault_ref,
                        "prev_public_cert_pem": global_tp.prev_public_cert_pem,
                        "prev_public_cert_vault_ref": global_tp.prev_public_cert_vault_ref,
                        "prev_private_key_vault_ref": global_tp.prev_private_key_vault_ref,
                        "url": global_tp.url,
                        "active": global_tp.active,
                        "created_at": global_tp.created_at,
                        "updated_at": global_tp.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_stmt)

        # --- AS2 Partnerships ---
        ps_stmt = select(GlobalAS2Partnership).where(
            (GlobalAS2Partnership.tenant_id == tenant_id) | (GlobalAS2Partnership.tenant_id == 0)
        )
        ps_result = await global_session.execute(ps_stmt)
        as2_partnerships = ps_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(as2_partnerships)} AS2 partnership(s)")

        for global_ps in as2_partnerships:
            logger.debug(
                f"[tenant={tenant_id}] Upserting AS2Partnership id={global_ps.id} name={global_ps.name!r}"
            )
            insert_ps_stmt = (
                insert(TenantAS2Partnership)
                .values(
                    id=global_ps.id,
                    tenant_id=tenant_id,
                    name=global_ps.name,
                    local_partner_id=global_ps.local_partner_id,
                    remote_partner_id=global_ps.remote_partner_id,
                    credentials_vault_ref=global_ps.credentials_vault_ref,
                    mdn_type=global_ps.mdn_type,
                    mdn_url=global_ps.mdn_url,
                    encryption_algorithm=global_ps.encryption_algorithm,
                    signature_algorithm=global_ps.signature_algorithm,
                    advanced_flags=global_ps.advanced_flags,
                    active=global_ps.active,
                    created_at=global_ps.created_at,
                    updated_at=global_ps.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": global_ps.name,
                        "local_partner_id": global_ps.local_partner_id,
                        "remote_partner_id": global_ps.remote_partner_id,
                        "credentials_vault_ref": global_ps.credentials_vault_ref,
                        "mdn_type": global_ps.mdn_type,
                        "mdn_url": global_ps.mdn_url,
                        "encryption_algorithm": global_ps.encryption_algorithm,
                        "signature_algorithm": global_ps.signature_algorithm,
                        "advanced_flags": global_ps.advanced_flags,
                        "active": global_ps.active,
                        "created_at": global_ps.created_at,
                        "updated_at": global_ps.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_ps_stmt)

        # --- SFTP Partners ---
        sftp_stmt = select(GlobalSFTPPartner).where(GlobalSFTPPartner.tenant_id == tenant_id)
        sftp_result = await global_session.execute(sftp_stmt)
        sftp_partners = sftp_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(sftp_partners)} SFTP partner(s)")

        for global_sftp in sftp_partners:
            logger.debug(
                f"[tenant={tenant_id}] Upserting SFTPPartner id={global_sftp.id} name={global_sftp.name!r}"
            )
            insert_sftp_stmt = (
                insert(TenantSFTPPartner)
                .values(
                    id=global_sftp.id,
                    tenant_id=tenant_id,
                    name=global_sftp.name,
                    host=global_sftp.host,
                    port=global_sftp.port,
                    username=global_sftp.username,
                    inbound_remote_path=global_sftp.inbound_remote_path,
                    outbound_remote_path=global_sftp.outbound_remote_path,
                    host_key=global_sftp.host_key,
                    password_encrypted=global_sftp.password_encrypted,
                    credentials_vault_ref=global_sftp.credentials_vault_ref,
                    active=global_sftp.active,
                    created_at=global_sftp.created_at,
                    updated_at=global_sftp.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": global_sftp.name,
                        "host": global_sftp.host,
                        "port": global_sftp.port,
                        "username": global_sftp.username,
                        "inbound_remote_path": global_sftp.inbound_remote_path,
                        "outbound_remote_path": global_sftp.outbound_remote_path,
                        "host_key": global_sftp.host_key,
                        "password_encrypted": global_sftp.password_encrypted,
                        "credentials_vault_ref": global_sftp.credentials_vault_ref,
                        "active": global_sftp.active,
                        "created_at": global_sftp.created_at,
                        "updated_at": global_sftp.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_sftp_stmt)

        # --- Webhooks ---
        wh_stmt = select(GlobalWebhook).where(GlobalWebhook.tenant_id == tenant_id)
        wh_result = await global_session.execute(wh_stmt)
        webhooks = wh_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(webhooks)} webhook(s)")

        for global_wh in webhooks:
            logger.debug(
                f"[tenant={tenant_id}] Upserting Webhook id={global_wh.id} name={global_wh.name!r}"
            )
            insert_wh_stmt = (
                insert(TenantWebhook)
                .values(
                    id=global_wh.id,
                    tenant_id=tenant_id,
                    name=global_wh.name,
                    url=global_wh.url,
                    auth_header_vault_ref=global_wh.auth_header_vault_ref,
                    active=global_wh.active,
                    created_at=global_wh.created_at,
                    updated_at=global_wh.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": global_wh.name,
                        "url": global_wh.url,
                        "auth_header_vault_ref": global_wh.auth_header_vault_ref,
                        "active": global_wh.active,
                        "created_at": global_wh.created_at,
                        "updated_at": global_wh.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_wh_stmt)

        # --- Inbound Routes ---
        ir_stmt = select(GlobalInboundRoute).where(GlobalInboundRoute.tenant_id == tenant_id)
        ir_result = await global_session.execute(ir_stmt)
        inbound_routes = ir_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(inbound_routes)} inbound route(s)")

        for global_ir in inbound_routes:
            logger.debug(
                f"[tenant={tenant_id}] Upserting InboundRoute id={global_ir.id} name={global_ir.name!r}"
            )
            insert_ir_stmt = (
                insert(TenantInboundRoute)
                .values(
                    id=global_ir.id,
                    tenant_id=tenant_id,
                    name=global_ir.name,
                    trading_partner_id=global_ir.trading_partner_id,
                    isa_sender_id=global_ir.isa_sender_id,
                    isa_receiver_id=global_ir.isa_receiver_id,
                    gs_sender_id=global_ir.gs_sender_id,
                    gs_receiver_id=global_ir.gs_receiver_id,
                    transaction_type=global_ir.transaction_type,
                    processing_mode=global_ir.processing_mode,
                    webhook_id=global_ir.webhook_id,
                    as2_partner_id=global_ir.as2_partner_id,
                    sftp_partner_id=global_ir.sftp_partner_id,
                    active=global_ir.active,
                    created_at=global_ir.created_at,
                    updated_at=global_ir.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": global_ir.name,
                        "trading_partner_id": global_ir.trading_partner_id,
                        "isa_sender_id": global_ir.isa_sender_id,
                        "isa_receiver_id": global_ir.isa_receiver_id,
                        "gs_sender_id": global_ir.gs_sender_id,
                        "gs_receiver_id": global_ir.gs_receiver_id,
                        "transaction_type": global_ir.transaction_type,
                        "processing_mode": global_ir.processing_mode,
                        "webhook_id": global_ir.webhook_id,
                        "as2_partner_id": global_ir.as2_partner_id,
                        "sftp_partner_id": global_ir.sftp_partner_id,
                        "active": global_ir.active,
                        "created_at": global_ir.created_at,
                        "updated_at": global_ir.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_ir_stmt)

        # --- Outbound Routes ---
        or_stmt = select(GlobalOutboundRoute).where(GlobalOutboundRoute.tenant_id == tenant_id)
        or_result = await global_session.execute(or_stmt)
        outbound_routes = or_result.scalars().all()
        logger.info(f"[tenant={tenant_id}] Replicating {len(outbound_routes)} outbound route(s)")

        for global_or in outbound_routes:
            logger.debug(
                f"[tenant={tenant_id}] Upserting OutboundRoute id={global_or.id} name={global_or.name!r}"
            )
            insert_or_stmt = (
                insert(TenantOutboundRoute)
                .values(
                    id=global_or.id,
                    tenant_id=tenant_id,
                    trading_partner_id=global_or.trading_partner_id,
                    name=global_or.name,
                    isa_sender_id=global_or.isa_sender_id,
                    isa_sender_qualifier=global_or.isa_sender_qualifier,
                    isa_receiver_id=global_or.isa_receiver_id,
                    isa_receiver_qualifier=global_or.isa_receiver_qualifier,
                    gs_sender_id=global_or.gs_sender_id,
                    gs_receiver_id=global_or.gs_receiver_id,
                    default_standard=global_or.default_standard,
                    default_version=global_or.default_version,
                    transaction_type=global_or.transaction_type,
                    processing_mode=global_or.processing_mode,
                    as2_partner_id=global_or.as2_partner_id,
                    sftp_partner_id=global_or.sftp_partner_id,
                    active=global_or.active,
                    created_at=global_or.created_at,
                    updated_at=global_or.updated_at,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "trading_partner_id": global_or.trading_partner_id,
                        "name": global_or.name,
                        "isa_sender_id": global_or.isa_sender_id,
                        "isa_sender_qualifier": global_or.isa_sender_qualifier,
                        "isa_receiver_id": global_or.isa_receiver_id,
                        "isa_receiver_qualifier": global_or.isa_receiver_qualifier,
                        "gs_sender_id": global_or.gs_sender_id,
                        "gs_receiver_id": global_or.gs_receiver_id,
                        "default_standard": global_or.default_standard,
                        "default_version": global_or.default_version,
                        "transaction_type": global_or.transaction_type,
                        "processing_mode": global_or.processing_mode,
                        "as2_partner_id": global_or.as2_partner_id,
                        "sftp_partner_id": global_or.sftp_partner_id,
                        "active": global_or.active,
                        "created_at": global_or.created_at,
                        "updated_at": global_or.updated_at,
                    },
                )
            )
            await tenant_session.execute(insert_or_stmt)

        # --- Sync deletes (children before parents) ---
        logger.info(f"[tenant={tenant_id}] Syncing deletes...")
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

    async def _sync_deletes(
        self,
        tenant_id: int,
        global_session: Any,
        tenant_session: Any,
        global_model: Any,
        tenant_model: Any,
        include_shared: bool,
    ) -> None:
        # Get all valid IDs from global
        global_stmt = select(global_model.id).where(global_model.tenant_id == tenant_id)
        # Special handling for global models (tenant_id = 0 or NULL)
        if include_shared:
            global_stmt = select(global_model.id).where(
                (global_model.tenant_id == tenant_id)
                | (global_model.tenant_id == 0)
                | (global_model.tenant_id.is_(None))
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
            delete_stmt = delete(tenant_model).where(tenant_model.id.in_(list(ids_to_delete)))
            await tenant_session.execute(delete_stmt)
        else:
            logger.debug(
                f"[tenant={tenant_id}] No stale {tenant_model.__tablename__} records to delete"
            )
