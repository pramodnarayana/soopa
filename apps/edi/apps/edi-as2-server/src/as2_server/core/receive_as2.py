import time
import uuid
from typing import Any

from as2_core import (
    AS2MDN,
    AS2Message,
    Disposition,
    generate_mdn,
)
from identity.domain.identity_context import PLATFORM_TENANT_ID
from observability import ObservabilityProvider
from security import decrypt_payload, verify_signature

from ..ports.repository import (
    IAS2TenantRepository,
    IEdiMessageRepository,
    ITradingPartnerRepository,
)
from ..ports.storage import IPayloadStorage
from ..ports.vault import IVaultService


class ReceiveAS2UseCase:
    def __init__(
        self,
        tenant_repo: IAS2TenantRepository,
        partner_repo: ITradingPartnerRepository,
        message_repo: IEdiMessageRepository,
        storage: IPayloadStorage,
        vault: IVaultService,
        db_router: Any = None,
        global_session: Any = None,
    ) -> None:
        self.tenant_repo = tenant_repo
        self.partner_repo = partner_repo
        self.message_repo = message_repo
        self.storage = storage
        self.vault = vault
        self.db_router = db_router
        self.global_session = global_session
        self.tracer = ObservabilityProvider.tracer()
        self.metrics = ObservabilityProvider.metrics()
        self.logger = ObservabilityProvider.logger(__name__)

    def _extract_isa_headers(self, pure_edi_bytes: bytes) -> tuple[str, str] | None:
        """
        Lightweight ISA parser to extract Sender and Receiver for routing
        without parsing the entire EDI structure.
        Requires the complete fixed-length ISA envelope (106 chars) and all 16 elements.
        """
        try:
            content = pure_edi_bytes.decode("ascii", strict=True)
            if not content.startswith("ISA"):
                return None

            # Require complete ISA envelope (106 bytes fixed length)
            if len(content) < 106:
                self.logger.warning("isa_extraction_failed", error="ISA segment truncated")
                return None

            element_separator = content[3]
            isa_segment = content[:106]
            elements = isa_segment.split(element_separator)

            # ISA split should have exactly 17 elements (ISA tag + 15 fields + 1 after terminator/field)
            # Actually, standard ISA is 106 chars: `ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *...~`
            # `elements` length will be 17 if we split on `*`.
            if len(elements) != 17:
                self.logger.warning("isa_extraction_failed", error="ISA element count invalid")
                return None

            # Enforce fixed field widths based on X12 standard
            if len(elements[6]) != 15 or len(elements[8]) != 15:
                self.logger.warning("isa_extraction_failed", error="ISA field widths invalid")
                return None

            isa_sender = elements[6].strip()
            isa_receiver = elements[8].strip()
            return isa_sender, isa_receiver
        except UnicodeDecodeError:
            self.logger.warning(
                "isa_extraction_failed", error="Non-ASCII characters in ISA segment"
            )
            return None
        except Exception as e:
            self.logger.warning("isa_extraction_failed", error=str(e))
            return None

    async def execute(self, as2_msg: AS2Message) -> AS2MDN:
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as stack:
            return await self._execute_inner(as2_msg, stack, self.message_repo)

    async def _execute_inner(
        self,
        as2_msg: AS2Message,
        async_exit_stack: Any,
        message_repo: IEdiMessageRepository,
    ) -> AS2MDN:
        start_time = time.perf_counter()

        tenant_id = None
        try:
            tenant_id = await self.tenant_repo.resolve_tenant_id(as2_msg.as2_to)
        except ValueError as e:
            self.logger.warning("tenant_resolution_ambiguous", error=str(e), as2_to=as2_msg.as2_to)

        if not tenant_id:
            self.metrics.increment("as2_verify_errors_total", labels={"tenant_id": "unknown"})
            self.logger.warning("as2_unknown_tenant", as2_to=as2_msg.as2_to)
            return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)

        logger = self.logger.bind(message_id=as2_msg.message_id, tenant_id=tenant_id)

        partner = await self.partner_repo.find_by_as2_id(tenant_id, as2_msg.as2_from)
        if not partner:
            self.metrics.increment("as2_verify_errors_total", labels={"tenant_id": str(tenant_id)})
            logger.warning("as2_unknown_partner", as2_from=as2_msg.as2_from)
            return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)

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

        processed_payload = as2_msg.payload
        disposition = Disposition.PROCESSED

        if as2_msg.is_encrypted:
            with self.tracer.start_span("as2.decrypt") as span:
                try:
                    private_key_pem = self.vault.get_host_private_key()
                    host_cert_pem = self.vault.get_host_certificate()
                    if not private_key_pem or not host_cert_pem:
                        raise ValueError("Host keys missing")

                    processed_payload = decrypt_payload(
                        as2_msg.raw_mime or b"", private_key_pem, host_cert_pem
                    )
                    logger.info("as2_decrypt_success")
                except Exception as e:
                    span.record_exception(e)
                    span.set_status_error("Decryption failed")
                    self.metrics.increment(
                        "as2_decrypt_errors_total", labels={"tenant_id": str(tenant_id)}
                    )
                    logger.error("as2_decrypt_failed", error=str(e))
                    disposition = Disposition.DECRYPTION_FAILED

        # The MIC MUST be calculated over the signed payload BEFORE signature verification (RFC 4130).
        # We capture the payload here (which is either the raw payload, or the decrypted signed payload)
        mic_payload = processed_payload

        if as2_msg.is_signed and "failed" not in disposition:
            with self.tracer.start_span("as2.verify_signature") as span:
                if not partner.public_cert_pem:
                    span.set_status_error("Partner certificate missing")
                    self.metrics.increment(
                        "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                    )
                    logger.warning("as2_partner_cert_missing", as2_from=as2_msg.as2_from)
                    disposition = Disposition.INSUFFICIENT_SECURITY
                else:
                    partner_cert = partner.public_cert_pem.encode("utf-8")
                    is_valid, verified_payload = verify_signature(processed_payload, partner_cert)
                    if not is_valid:
                        span.set_status_error("Signature invalid")
                        self.metrics.increment(
                            "as2_verify_errors_total", labels={"tenant_id": str(tenant_id)}
                        )
                        logger.warning("as2_signature_invalid")
                        disposition = Disposition.AUTHENTICATION_FAILED
                    else:
                        processed_payload = verified_payload
                        logger.info("as2_signature_verified")

        routed_tenant_session = None

        # Dynamic Tenant Resolution via ISA payload routing
        if tenant_id == str(PLATFORM_TENANT_ID) and "failed" not in disposition:
            with self.tracer.start_span("as2.isa_routing"):
                isa_headers = self._extract_isa_headers(processed_payload)
                if isa_headers:
                    isa_sender, isa_receiver = isa_headers
                    try:
                        true_tenant_id = await self.tenant_repo.resolve_tenant_by_edi_identifiers(
                            isa_sender, isa_receiver
                        )
                        if true_tenant_id:
                            # 1. Check if we have the necessary DB setup tools
                            if not self.db_router or not self.global_session:
                                logger.error(
                                    "as2_isa_routing_failed_no_db_tools",
                                    isa_sender=isa_sender,
                                    isa_receiver=isa_receiver,
                                )
                                return generate_mdn(
                                    as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY
                                )

                            # 2. Resolve shard row
                            from database.models import DatabaseShard, Tenant
                            from sqlalchemy import select

                            stmt = (
                                select(Tenant, DatabaseShard)
                                .join(DatabaseShard)
                                .where(Tenant.id == true_tenant_id)
                            )
                            result = await self.global_session.execute(stmt)
                            row = result.first()

                            if not row:
                                logger.error(
                                    "as2_isa_routing_failed_no_shard_row",
                                    true_tenant_id=true_tenant_id,
                                )
                                return generate_mdn(
                                    as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY
                                )

                            tenant_obj, shard_obj = row

                            # 3. Setup tenant session
                            tenant_session_gen = self.db_router.get_tenant_session(
                                tenant_id=tenant_obj.id,
                                shard_key=str(shard_obj.name),
                                shard_url=str(shard_obj.dsn),
                            )

                            from contextlib import aclosing

                            await async_exit_stack.enter_async_context(aclosing(tenant_session_gen))

                            try:
                                tenant_session = await tenant_session_gen.__anext__()
                            except StopAsyncIteration:
                                logger.error("as2_isa_routing_failed_session_empty")
                                return generate_mdn(
                                    as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY
                                )

                            # 4. Resolve the repository
                            from ..adapters.repository import EdiMessageRepositoryAdapter

                            new_repo = EdiMessageRepositoryAdapter(tenant_session)

                            # 5. Success! Now apply the changes to the flow state
                            tenant_id = true_tenant_id
                            logger = self.logger.bind(
                                message_id=as2_msg.message_id, tenant_id=tenant_id
                            )
                            message_repo = new_repo
                            routed_tenant_session = tenant_session

                            logger.info(
                                "as2_isa_routed_tenant",
                                isa_sender=isa_sender,
                                isa_receiver=isa_receiver,
                                true_tenant_id=tenant_id,
                            )
                        else:
                            logger.warning(
                                "as2_isa_routing_failed_unmatched",
                                isa_sender=isa_sender,
                                isa_receiver=isa_receiver,
                            )
                    except ValueError as e:
                        logger.error(
                            "as2_isa_routing_ambiguous",
                            error=str(e),
                            isa_sender=isa_sender,
                            isa_receiver=isa_receiver,
                        )
                        return generate_mdn(as2_msg, disposition=Disposition.INSUFFICIENT_SECURITY)

        with self.tracer.start_span("as2.s3_upload"):
            # Upload the inner EDI payload (after decryption and verification extraction)
            storage_uri = await self.storage.upload(
                tenant_id, as2_msg.message_id, processed_payload
            )

        with self.tracer.start_span("as2.db_persist"):
            status = "ERROR" if "failed" in disposition else "RECEIVED"
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
            except Exception as e:
                if routed_tenant_session:
                    await routed_tenant_session.rollback()
                raise e

        # generate_mdn calculates the MIC using as2_msg.payload
        as2_msg.payload = mic_payload
        mdn = generate_mdn(as2_msg, disposition=disposition)

        duration = time.perf_counter() - start_time
        self.metrics.observe(
            "as2_message_processing_seconds", duration, labels={"tenant_id": str(tenant_id)}
        )
        self.metrics.increment(
            "as2_mdn_sent_total",
            labels={
                "tenant_id": str(tenant_id),
                "disposition": "processed" if "failed" not in disposition else "failed",
            },
        )
        logger.info("as2_mdn_sent", disposition=disposition, duration_ms=round(duration * 1000, 2))

        return mdn
