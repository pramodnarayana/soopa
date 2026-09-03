import time
import uuid
from contextlib import AsyncExitStack, aclosing
from dataclasses import dataclass
from typing import Any

from database.models.identity import Tenant
from edi.adapters.outbound.security import decrypt_payload, verify_signature
from edi.domain.models.as2 import (
    AS2MDN,
    AS2Message,
    Disposition,
)
from edi.domain.services.as2_protocol import generate_mdn
from identity.domain.identity_context import PLATFORM_TENANT_ID
from observability import ObservabilityProvider
from sqlalchemy import select
from ucp_models.infrastructure import DatabaseShard

from as2_server.ports.outbound.repository_port import (
    AS2TenantRepositoryPort,
    EdiMessageRepositoryPort,
    TradingPartnerRepositoryPort,
)
from as2_server.ports.outbound.storage_port import PayloadStoragePort
from as2_server.ports.outbound.vault_port import VaultServicePort

from ...adapters.outbound.repository import EdiMessageRepositoryAdapter


@dataclass(frozen=True)
class _RouteResult:
    failed: bool
    tenant_id: str | None = None
    message_repo: EdiMessageRepositoryPort | None = None
    session: Any = None


class ReceiveAS2UseCase:
    def __init__(
        self,
        tenant_repo: AS2TenantRepositoryPort,
        partner_repo: TradingPartnerRepositoryPort,
        message_repo: EdiMessageRepositoryPort,
        storage: PayloadStoragePort,
        vault: VaultServicePort,
        db_router: Any = None,
        global_session: Any = None,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.partner_repo = partner_repo
        self.message_repo = message_repo
        self.storage = storage
        self.secret_store = vault
        self.db_router = db_router
        self.global_session = global_session
        self.tracer = ObservabilityProvider.tracer()
        self.metrics = ObservabilityProvider.metrics()
        self.logger = ObservabilityProvider.logger(__name__)

    def _extract_isa_headers(self, pure_edi_bytes: bytes) -> tuple[str, str] | None:
        try:
            content = pure_edi_bytes[:106].decode("ascii", errors="strict")
            if not content.startswith("ISA") or len(content) < 106:
                self.logger.warning(
                    "isa_extraction_failed", error="ISA segment missing or truncated"
                )
                return None

            element_separator = content[3]
            elements = content[:106].split(element_separator)

            if len(elements) != 17 or len(elements[6]) != 15 or len(elements[8]) != 15:
                self.logger.warning(
                    "isa_extraction_failed", error="ISA element count or widths invalid"
                )
                return None

            return elements[6].strip(), elements[8].strip()
        except Exception as e:  # noqa: BLE001
            self.logger.warning("isa_extraction_failed", error=str(e))
            return None

    async def execute(self, as2_msg: AS2Message) -> AS2MDN:

        async with AsyncExitStack() as stack:
            return await self._execute_inner(as2_msg, stack, self.message_repo)

    async def _execute_inner(
        self,
        as2_msg: AS2Message,
        async_exit_stack: Any,
        message_repo: EdiMessageRepositoryPort,
    ) -> AS2MDN:
        start_time = time.perf_counter()

        tenant_id = await self._resolve_initial_tenant(as2_msg)
        if not tenant_id:
            return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)

        logger = self.logger.bind(message_id=as2_msg.message_id, tenant_id=tenant_id)

        partner = await self.partner_repo.find_by_as2_id(str(tenant_id), as2_msg.as2_from)
        if not partner:
            self.metrics.increment("as2_verify_errors_total", labels={"tenant_id": str(tenant_id)})
            logger.warning("as2_unknown_partner", as2_from=as2_msg.as2_from)
            return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)

        self._record_message_received(tenant_id, as2_msg, logger)

        processed_payload = as2_msg.payload
        disposition = Disposition.PROCESSED

        if as2_msg.is_encrypted:
            processed_payload, disp_update = self._decrypt_payload(as2_msg, tenant_id, logger)
            if "failed" in disp_update.value:
                disposition = disp_update

        mic_payload = processed_payload

        if as2_msg.is_signed and "failed" not in disposition.value:
            processed_payload, disp_update = self._verify_signature(
                as2_msg, partner, processed_payload, tenant_id, logger
            )
            if "failed" in disp_update.value:
                disposition = disp_update

        routed_tenant_session = None

        if tenant_id == str(PLATFORM_TENANT_ID) and "failed" not in disposition.value:
            route_result = await self._route_tenant(
                as2_msg, processed_payload, tenant_id, async_exit_stack, logger
            )
            if route_result.failed or not route_result.tenant_id or not route_result.message_repo:
                return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)
            tenant_id = route_result.tenant_id
            message_repo = route_result.message_repo
            routed_tenant_session = route_result.session
            logger = self.logger.bind(message_id=as2_msg.message_id, tenant_id=tenant_id)

        with self.tracer.start_span("as2.s3_upload"):
            storage_uri = await self.storage.upload(
                str(tenant_id), as2_msg.message_id, processed_payload
            )

        await self._persist_message(
            tenant_id, as2_msg, disposition, storage_uri, message_repo, routed_tenant_session
        )

        as2_msg.payload = mic_payload
        mdn = generate_mdn(as2_msg, disposition=disposition)

        self._record_metrics(tenant_id, disposition, start_time, logger)
        return mdn

    async def _resolve_initial_tenant(self, as2_msg: AS2Message) -> str | None:
        try:
            tenant_id = await self.tenant_repo.resolve_tenant_id(as2_msg.as2_to)
            if not tenant_id:
                self.metrics.increment("as2_verify_errors_total", labels={"tenant_id": "unknown"})
                self.logger.warning("as2_unknown_tenant", as2_to=as2_msg.as2_to)
                return None
            return str(tenant_id)
        except ValueError as e:
            self.logger.warning("tenant_resolution_ambiguous", error=str(e), as2_to=as2_msg.as2_to)
            self.metrics.increment("as2_verify_errors_total", labels={"tenant_id": "unknown"})
            return None

    def _record_message_received(self, tenant_id: str, as2_msg: AS2Message, logger: Any) -> None:
        self.metrics.increment(
            "as2_messages_received_total",
            labels={
                "tenant_id": str(tenant_id),
                "as2_from": as2_msg.as2_from,
                "as2_to": as2_msg.as2_to,
            },
        )
        logger.info(
            "as2_message_received", is_encrypted=as2_msg.is_encrypted, is_signed=as2_msg.is_signed
        )

    def _decrypt_payload(
        self, as2_msg: AS2Message, tenant_id: str, logger: Any
    ) -> tuple[bytes, Disposition]:
        with self.tracer.start_span("as2.decrypt") as span:
            try:
                private_key_pem = self.secret_store.get_host_private_key()
                host_cert_pem = self.secret_store.get_host_certificate()
                if not private_key_pem or not host_cert_pem:
                    raise ValueError("Host keys missing")

                payload = decrypt_payload(as2_msg.raw_mime or b"", private_key_pem, host_cert_pem)
                logger.info("as2_decrypt_success")
                return payload, Disposition.PROCESSED
            except Exception as e:
                span.record_exception(e)
                span.set_status_error("Decryption failed")
                self.metrics.increment(
                    "as2_decrypt_errors_total", labels={"tenant_id": str(tenant_id)}
                )
                logger.exception("as2_decrypt_failed", error=str(e))
                return as2_msg.payload, Disposition.DECRYPTION_FAILED

    def _verify_signature(
        self, as2_msg: AS2Message, partner: Any, payload: bytes, tenant_id: str, logger: Any
    ) -> tuple[bytes, Disposition]:
        with self.tracer.start_span("as2.verify_signature") as span:
            if not partner.public_cert_pem:
                span.set_status_error("Partner certificate missing")
                self.metrics.increment(
                    "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                )
                logger.warning("as2_partner_cert_missing", as2_from=as2_msg.as2_from)
                return payload, Disposition.INSUFFICIENT_SECURITY

            is_valid, verified_payload = verify_signature(
                payload, partner.public_cert_pem.encode("utf-8")
            )
            if not is_valid:
                span.set_status_error("Signature invalid")
                self.metrics.increment(
                    "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                )
                logger.warning("as2_signature_invalid")
                return payload, Disposition.AUTHENTICATION_FAILED

            logger.info("as2_signature_verified")
            return verified_payload, Disposition.PROCESSED

    async def _route_tenant(
        self,
        as2_msg: AS2Message,
        payload: bytes,
        tenant_id: str,
        async_exit_stack: Any,
        logger: Any,
    ) -> _RouteResult:
        with self.tracer.start_span("as2.isa_routing"):
            isa_headers = self._extract_isa_headers(payload)
            if not isa_headers:
                return _RouteResult(failed=False, tenant_id=tenant_id)

            isa_sender, isa_receiver = isa_headers
            try:
                true_tenant_id = await self.tenant_repo.resolve_tenant_by_edi_identifiers(
                    as2_peer_id=as2_msg.as2_from, isa_sender=isa_sender, isa_receiver=isa_receiver
                )
                if not true_tenant_id:
                    logger.warning(
                        "as2_isa_routing_failed_unmatched",
                        isa_sender=isa_sender,
                        isa_receiver=isa_receiver,
                    )
                    return _RouteResult(failed=False, tenant_id=tenant_id)

                if not self.db_router or not self.global_session:
                    logger.error(
                        "as2_isa_routing_failed_no_db_tools",
                        isa_sender=isa_sender,
                        isa_receiver=isa_receiver,
                    )
                    return _RouteResult(failed=True)

                stmt = (
                    select(Tenant, DatabaseShard)
                    .join(DatabaseShard)
                    .where(Tenant.id == true_tenant_id)
                )
                row = (await self.global_session.execute(stmt)).first()

                if not row:
                    logger.error(
                        "as2_isa_routing_failed_no_shard_row", true_tenant_id=true_tenant_id
                    )
                    return _RouteResult(failed=True)

                tenant_obj, shard_obj = row
                tenant_session_gen = self.db_router.get_tenant_session(
                    tenant_id=tenant_obj.id,
                    shard_key=str(shard_obj.name),
                    shard_url=str(shard_obj.dsn),
                )

                await async_exit_stack.enter_async_context(aclosing(tenant_session_gen))

                try:
                    tenant_session = await tenant_session_gen.__anext__()
                except StopAsyncIteration:
                    logger.exception("as2_isa_routing_failed_session_empty")
                    return _RouteResult(failed=True)

                new_repo = EdiMessageRepositoryAdapter(tenant_session)

                partner = await self.partner_repo.find_by_as2_id(true_tenant_id, as2_msg.as2_from)
                if not partner or not partner.active:
                    logger.warning("as2_isa_routed_partner_missing", as2_from=as2_msg.as2_from)
                    return _RouteResult(failed=True)

                logger.info(
                    "as2_isa_routed_tenant",
                    isa_sender=isa_sender,
                    isa_receiver=isa_receiver,
                    true_tenant_id=true_tenant_id,
                )
                return _RouteResult(
                    failed=False,
                    tenant_id=true_tenant_id,
                    message_repo=new_repo,
                    session=tenant_session,
                )

            except ValueError as e:
                logger.exception(
                    "as2_isa_routing_ambiguous",
                    error=str(e),
                    isa_sender=isa_sender,
                    isa_receiver=isa_receiver,
                )
                return _RouteResult(failed=True)

    async def _persist_message(
        self,
        tenant_id: str,
        as2_msg: AS2Message,
        disposition: Disposition,
        storage_uri: str,
        message_repo: Any,
        routed_tenant_session: Any,
    ) -> None:
        with self.tracer.start_span("as2.db_persist"):
            status = "ERROR" if "failed" in disposition.value else "RECEIVED"
            trace_id = uuid.uuid4()
            try:
                await message_repo.save_message(
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    direction="INBOUND",
                    connection_type="AS2",
                    sender_id=as2_msg.as2_from,
                    receiver_id=as2_msg.as2_to,
                    edi_data=storage_uri,
                    status=status,
                    as2_message_id=as2_msg.message_id,
                )
                if routed_tenant_session:
                    await routed_tenant_session.commit()
            except Exception:
                if routed_tenant_session:
                    await routed_tenant_session.rollback()
                raise

    def _record_metrics(
        self, tenant_id: str, disposition: Disposition, start_time: float, logger: Any
    ) -> None:
        duration = time.perf_counter() - start_time
        self.metrics.observe(
            "as2_message_processing_seconds", duration, labels={"tenant_id": str(tenant_id)}
        )
        self.metrics.increment(
            "as2_mdn_sent_total",
            labels={
                "tenant_id": str(tenant_id),
                "disposition": "processed" if "failed" not in disposition.value else "failed",
            },
        )
        logger.info("as2_mdn_sent", disposition=disposition, duration_ms=round(duration * 1000, 2))
