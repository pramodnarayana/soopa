import uuid
from datetime import UTC, datetime
from typing import Any

from config.settings import AppSettings
from database.constants import (
    API_GATEWAY_ID_PREFIX,
    DATA_PLANE_OUTBOX_EVENT_PREFIX,
    EDI_JSON_ID_PREFIX,
    EDI_MESSAGE_ID_PREFIX,
)
from database.encryption import db_encryption
from database.models import ApiGateway, EdiMessage
from database.models import DataPlaneOutbox as Outbox
from database.models.data_plane import (
    AS2Partner,
    AS2Partnership,
    InboundRoute,
    OutboundRoute,
    SFTPPartner,
    Webhook,
)
from domain.models import EdiJsonDomainModel, EdiMessageDomainModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.ports.repository import RepositoryPort
from pipeline.ports.storage import StoragePort


class SqlAlchemyRepositoryAdapter(RepositoryPort):
    """
    Concrete implementation of RepositoryPort using SQLAlchemy AsyncSession.
    Operates on the Tenant Data Plane models.
    """

    def __init__(self, session: AsyncSession, settings: AppSettings, storage: StoragePort):
        self.session = session
        self.settings = settings
        self.storage = storage

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
        result = await self.session.execute(
            select(EdiMessage)
            .where(EdiMessage.trace_id == str(trace_id))
            .order_by(EdiMessage.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        edi_data = record.edi_data
        if record.storage_uri:
            raw_bytes = await self.storage.download(record.storage_uri)
            edi_data = raw_bytes.decode("utf-8")

        domain_model = EdiMessageDomainModel.model_validate(record)
        domain_model.edi_data = edi_data
        return domain_model

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        stmt = (
            update(EdiMessage)
            .where(
                EdiMessage.id
                == (
                    select(EdiMessage.id)
                    .where(EdiMessage.trace_id == str(trace_id))
                    .order_by(EdiMessage.created_at.desc())
                    .limit(1)
                    .scalar_subquery()
                )
            )
            .values(status=status, updated_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str,
        gs_receiver_id: str,
        transaction_type: str | None = None,
    ) -> None:
        values_to_update = {"gs_sender_id": gs_sender_id, "gs_receiver_id": gs_receiver_id}
        if transaction_type:
            values_to_update["transaction_type"] = transaction_type

        stmt = (
            update(EdiMessage)
            .where(
                EdiMessage.id
                == (
                    select(EdiMessage.id)
                    .where(EdiMessage.trace_id == str(trace_id))
                    .order_by(EdiMessage.created_at.desc())
                    .limit(1)
                    .scalar_subquery()
                )
            )
            .values(**values_to_update)
        )
        await self.session.execute(stmt)

    async def save_edi_message(
        self,
        trace_id: str,
        direction: str,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
        status: str,
        connection_type: str | None = "UNKNOWN",
        sender_id: str | None = None,
        receiver_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        trading_partner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        storage_uri = None
        data_to_store = edi_data
        if self.settings.storage_backend == "s3":
            storage_uri = await self.storage.upload(
                payload=edi_data.encode("utf-8"),
                key_prefix=f"edi_messages/{trace_id}",
                file_name="payload.edi",
            )
            data_to_store = ""

        record_kwargs = {
            "trace_id": str(trace_id),
            "direction": direction,
            "connection_type": connection_type,
            "edi_data": data_to_store,
            "format_standard": format_standard,
            "transaction_type": transaction_type,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "gs_sender_id": gs_sender_id,
            "gs_receiver_id": gs_receiver_id,
            "storage_uri": storage_uri,
            "status": status,
            "trading_partner_id": trading_partner_id,
        }
        if tenant_id is not None:
            record_kwargs["tenant_id"] = tenant_id

        if "id" not in record_kwargs:
            record_kwargs["id"] = f"{EDI_MESSAGE_ID_PREFIX}{uuid.uuid4().hex}"

        record = EdiMessage(**record_kwargs)
        self.session.add(record)
        await self.session.flush()

    async def save_edi_json(
        self,
        trace_id: str,
        direction: str,
        partnership_id: str | None,
        transaction_type: str | None,
        standard: str | None,
        sender_id: str | None,
        receiver_id: str | None,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        business_metadata: dict[str, Any],
        payload: dict[str, Any],
        status: str,
        tenant_id: str | None = None,
    ) -> str:
        import json

        from database.models.data_plane import EdiJson

        payload_dict = payload
        storage_uri = None
        if self.settings.storage_backend == "s3":
            storage_uri = await self.storage.upload(
                payload=json.dumps(payload).encode("utf-8"),
                key_prefix=f"edi_json/{trace_id}",
                file_name="payload.json",
            )
            payload_dict = {}

        # Idempotency check
        stmt = (
            select(EdiJson.id)
            .where(
                EdiJson.trace_id == str(trace_id),
                EdiJson.direction == direction,
                EdiJson.transaction_type == transaction_type,
                EdiJson.business_metadata == business_metadata,
            )
            .limit(1)
        )
        existing_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing_id:
            return str(existing_id)

        record_kwargs = {
            "trace_id": str(trace_id),
            "direction": direction,
            "trading_partner_id": partnership_id,
            "transaction_type": transaction_type,
            "standard": standard,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "gs_sender_id": gs_sender_id,
            "gs_receiver_id": gs_receiver_id,
            "business_metadata": business_metadata,
            "payload": payload_dict,
            "storage_uri": storage_uri,
            "status": status,
        }
        if tenant_id is not None:
            record_kwargs["tenant_id"] = tenant_id

        if "id" not in record_kwargs:
            record_kwargs["id"] = f"{EDI_JSON_ID_PREFIX}{uuid.uuid4().hex}"

        record = EdiJson(**record_kwargs)
        self.session.add(record)
        await self.session.flush()
        return str(record.id)

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        from database.models.data_plane import EdiJson

        result = await self.session.execute(
            select(EdiJson)
            .where(EdiJson.trace_id == str(trace_id))
            .order_by(EdiJson.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        payload = record.payload
        if record.storage_uri:
            import json

            raw_bytes = await self.storage.download(record.storage_uri)
            payload = json.loads(raw_bytes.decode("utf-8"))

        domain_model = EdiJsonDomainModel.model_validate(record)
        domain_model.payload = payload
        return domain_model

    async def update_edi_json_status(self, trace_id: str, status: str) -> None:
        from database.models.data_plane import EdiJson

        await self.session.execute(
            update(EdiJson).where(EdiJson.trace_id == str(trace_id)).values(status=status)
        )
        await self.session.flush()

    async def update_edi_json(self, trace_id: str, **kwargs: Any) -> None:
        from database.models.data_plane import EdiJson

        if not kwargs:
            return
        await self.session.execute(
            update(EdiJson).where(EdiJson.trace_id == str(trace_id)).values(**kwargs)
        )
        await self.session.flush()

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, Any]
    ) -> None:

        stmt = (
            insert(Outbox)
            .values(
                id=f"{DATA_PLANE_OUTBOX_EVENT_PREFIX}{uuid.uuid4().hex}",
                idempotency_key=str(idempotency_key),
                event_type=event_type,
                payload=payload,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def claim_edi_message(self, trace_id: str) -> bool:
        stmt = (
            update(EdiMessage)
            .where(
                EdiMessage.id
                == (
                    select(EdiMessage.id)
                    .where(
                        EdiMessage.trace_id == str(trace_id),
                        EdiMessage.status == "PENDING_DELIVERY",
                    )
                    .order_by(EdiMessage.created_at.desc())
                    .limit(1)
                    .scalar_subquery()
                )
            )
            .values(status="PROCESSING")
            .returning(EdiMessage.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def save_api_payload(
        self,
        trace_id: str,
        direction: str,
        payload: dict[str, Any],
        status: str,
        transaction_type: str | None = None,
        webhook_url: str | None = None,
    ) -> None:

        from database.models.data_plane import ApiGateway

        # Idempotency check
        stmt = (
            select(ApiGateway.id)
            .where(
                ApiGateway.trace_id == str(trace_id),
                ApiGateway.direction == direction,
                ApiGateway.payload == payload,
            )
            .limit(1)
        )
        if (await self.session.execute(stmt)).scalar_one_or_none():
            return  # Skip insert

        record = ApiGateway(
            id=f"{API_GATEWAY_ID_PREFIX}{uuid.uuid4().hex}",
            trace_id=str(trace_id),
            direction=direction,
            transaction_type=transaction_type,
            payload=payload,
            status=status,
            webhook_url=webhook_url,
            http_status_code=202,
        )
        self.session.add(record)
        await self.session.flush()

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(ApiGateway)
            .where(ApiGateway.trace_id == str(trace_id))
            .order_by(ApiGateway.created_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        payload = record.payload
        if record.storage_uri:
            import json

            raw_bytes = await self.storage.download(record.storage_uri)
            payload = json.loads(raw_bytes.decode("utf-8"))

        return {
            "trace_id": str(record.trace_id),
            "payload": payload,
            "status": record.status,
            "direction": record.direction,
        }

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        if webhook_url is not None:
            values["webhook_url"] = webhook_url
        if http_status_code is not None:
            values["http_status_code"] = http_status_code
        if response is not None:
            values["response"] = response

        await self.session.execute(
            update(ApiGateway).where(ApiGateway.trace_id == str(trace_id)).values(**values)
        )
        await self.session.flush()

    async def claim_api_payload(self, trace_id: str) -> bool:
        stmt = (
            update(ApiGateway)
            .where(
                ApiGateway.id
                == (
                    select(ApiGateway.id)
                    .where(
                        ApiGateway.trace_id == str(trace_id),
                        ApiGateway.status == "PENDING_DELIVERY",
                    )
                    .order_by(ApiGateway.created_at.desc())
                    .limit(1)
                    .scalar_subquery()
                )
            )
            .values(status="PROCESSING")
            .returning(ApiGateway.id)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def get_route(
        self,
        direction: str,
        sender_id: str,
        receiver_id: str,
        transaction_type: str,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
    ) -> dict[str, Any] | None:
        from typing import cast

        if direction not in ("INBOUND", "OUTBOUND"):
            raise ValueError(f"Invalid direction: {direction}")
        model = InboundRoute if direction == "INBOUND" else OutboundRoute

        # Exact match or wildcard transaction type
        conditions = [
            cast(Any, model).isa_sender_id == sender_id,
            cast(Any, model).isa_receiver_id == receiver_id,
            cast(Any, model).transaction_type.in_([transaction_type, "*"]),
            cast(Any, model).active.is_(True),
        ]

        if gs_sender_id:
            conditions.append(cast(Any, model).gs_sender_id == gs_sender_id)
        if gs_receiver_id:
            conditions.append(cast(Any, model).gs_receiver_id == gs_receiver_id)

        stmt = select(model).where(*conditions)

        result = await self.session.execute(stmt)
        # Fetch all matches, prefer exact transaction_type over wildcard
        records = list(result.scalars().all())
        if not records:
            return None

        # Sort so specific transaction types match before generic "*"
        records = sorted(records, key=lambda r: getattr(r, "transaction_type", "*") == "*")

        # mypy gets confused by TenantBase being the base class but returning specific derived models
        record: Any = records[0]
        return {
            "route_id": str(record.id),
            "trading_partner_id": getattr(record, "trading_partner_id", None),
            "as2_partner_id": str(record.as2_partner_id) if record.as2_partner_id else None,
            "sftp_partner_id": str(record.sftp_partner_id) if record.sftp_partner_id else None,
            "webhook_id": str(record.webhook_id)
            if hasattr(record, "webhook_id") and record.webhook_id
            else None,
        }

    async def get_outbound_route(self, route_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(OutboundRoute).where(OutboundRoute.id == str(route_id))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "id": str(record.id),
            "tenant_id": record.tenant_id,
            "trading_partner_id": record.trading_partner_id,
            "sftp_partner_id": str(record.sftp_partner_id) if record.sftp_partner_id else None,
            "as2_partner_id": str(record.as2_partner_id) if record.as2_partner_id else None,
        }

    async def get_outbound_route_by_trading_partner_id(
        self, trading_partner_id: str, tenant_id: str
    ) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.trading_partner_id == trading_partner_id,
                OutboundRoute.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "id": str(record.id),
            "tenant_id": record.tenant_id,
            "trading_partner_id": record.trading_partner_id,
            "sftp_partner_id": str(record.sftp_partner_id) if record.sftp_partner_id else None,
            "as2_partner_id": str(record.as2_partner_id) if record.as2_partner_id else None,
        }

    async def get_outbound_edi_header_by_route_or_partner(
        self,
        route_id: str | None = None,
        trading_partner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        from database.models.data_plane import OutboundEdiHeader, OutboundRoute

        query = select(OutboundEdiHeader)
        if route_id:
            route_query = select(OutboundRoute.trading_partner_id, OutboundRoute.tenant_id).where(
                OutboundRoute.id == str(route_id)
            )
            if tenant_id is not None:
                route_query = route_query.where(OutboundRoute.tenant_id == tenant_id)

            route_result = await self.session.execute(route_query)
            route_record = route_result.first()
            if not route_record:
                return None
            query = query.where(
                OutboundEdiHeader.trading_partner_id == route_record.trading_partner_id,
                OutboundEdiHeader.tenant_id == route_record.tenant_id,
            )
            if tenant_id is not None:
                query = query.where(OutboundEdiHeader.tenant_id == tenant_id)
        elif trading_partner_id and tenant_id is not None:
            query = query.where(
                OutboundEdiHeader.trading_partner_id == trading_partner_id,
                OutboundEdiHeader.tenant_id == tenant_id,
            )
        else:
            return None

        result = await self.session.execute(query)
        record = result.scalar_one_or_none()
        if not record:
            return None

        return {
            "id": str(record.id),
            "tenant_id": record.tenant_id,
            "trading_partner_id": record.trading_partner_id,
            "default_standard": record.default_standard,
            "default_version": record.default_version,
            "isa_sender_qualifier": record.isa_sender_qualifier,
            "isa_sender_id": record.isa_sender_id,
            "isa_receiver_qualifier": record.isa_receiver_qualifier,
            "isa_receiver_id": record.isa_receiver_id,
            "gs_sender_id": record.gs_sender_id,
            "gs_receiver_id": record.gs_receiver_id,
            "transaction_type": record.transaction_type,
        }

    async def get_sftp_partner(self, partner_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == str(partner_id), SFTPPartner.active.is_(True)
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "host": record.host,
            "port": record.port,
            "username": record.username,
            "inbound_remote_path": record.inbound_remote_path,
            "outbound_remote_path": record.outbound_remote_path,
            "host_key": record.host_key,
            "password": db_encryption.decrypt(record.password_encrypted)
            if record.password_encrypted
            else None,
            "credentials_vault_ref": record.credentials_vault_ref,
        }

    async def get_webhook(self, partner_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(Webhook).where(Webhook.id == str(partner_id), Webhook.active.is_(True))
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "url": record.url,
            "auth_header_vault_ref": record.auth_header_vault_ref,
        }

    async def get_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        stmt = (
            select(AS2Partner, AS2Partnership)
            .join(AS2Partnership, AS2Partnership.remote_partner_id == AS2Partner.id)
            .where(
                AS2Partner.id == str(partner_id),
                AS2Partner.active.is_(True),
                AS2Partnership.active.is_(True),
            )
        )
        result = await self.session.execute(stmt)
        record = result.first()
        if not record:
            return None
        partner, partnership = record
        return {
            "name": partner.name,
            "as2_id": partner.as2_id,
            "public_cert_pem": partner.public_cert_pem,
            "public_cert_vault_ref": partner.public_cert_vault_ref,
            "remote_url": partner.url,
            "local_partner_id": str(partnership.local_partner_id),
            "credentials_vault_ref": partnership.credentials_vault_ref,
            "encryption_algorithm": partnership.encryption_algorithm,
            "signature_algorithm": partnership.signature_algorithm,
            "mdn_type": partnership.mdn_type,
            "mdn_url": partnership.mdn_url,
        }

    async def get_local_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        """Fetches the local (our) AS2 partner to retrieve signing key and cert refs."""
        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.id == str(partner_id),
                AS2Partner.active.is_(True),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        return {
            "name": record.name,
            "as2_id": record.as2_id,
            "public_cert_pem": record.public_cert_pem,
            "public_cert_vault_ref": record.public_cert_vault_ref,
            "private_key_vault_ref": record.private_key_vault_ref,
        }
