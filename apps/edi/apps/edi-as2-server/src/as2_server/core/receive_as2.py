import time
import uuid

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
        db_router=None,
        global_session=None,
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
            content = pure_edi_bytes.decode("ascii", errors="ignore")
            if not content.startswith("ISA"):
                return None

            # Require complete ISA envelope (106 bytes fixed length)
            if len(content) < 106:
                self.logger.warning("isa_extraction_failed", error="ISA segment truncated")
                return None

            element_separator = content[3]
            isa_segment = content[:106]
            elements = isa_segment.split(element_separator)

            # ISA must have exactly 16 elements (ISA01-ISA16)
            if len(elements) < 16:
                self.logger.warning("isa_extraction_failed", error="ISA missing required elements")
                return None

            isa_sender = elements[6].strip()
            isa_receiver = elements[8].strip()
            return isa_sender, isa_receiver
        except Exception as e:
            self.logger.warning("isa_extraction_failed", error=str(e))
            return None

    async def execute(self, as2_msg: AS2Message) -> AS2MDN:
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
                            tenant_id = true_tenant_id
                            logger = self.logger.bind(
                                message_id=as2_msg.message_id, tenant_id=tenant_id
                            )
                            logger.info(
                                "as2_isa_routed_tenant",
                                isa_sender=isa_sender,
                                isa_receiver=isa_receiver,
                                true_tenant_id=tenant_id,
                            )

                            # Recreate message_repo with a session for the resolved tenant
                            if self.db_router and self.global_session:
                                from sqlalchemy import select
                                from database.models import DatabaseShard, Tenant
                                from ..adapters.repository import EdiMessageRepositoryAdapter
                                import contextlib

                                stmt = select(Tenant, DatabaseShard).join(DatabaseShard).where(
                                    Tenant.id == int(tenant_id)
                                )
                                result = await self.global_session.execute(stmt)
                                row = result.first()
                                if row:
                                    tenant_obj, shard_obj = row
                                    tenant_session_gen = self.db_router.get_tenant_session(
                                        tenant_id=int(tenant_obj.id),
                                        shard_key=str(shard_obj.name),
                                        shard_url=str(shard_obj.dsn),
                                    )
                                    tenant_session = await tenant_session_gen.__anext__()
                                    self.message_repo = EdiMessageRepositoryAdapter(tenant_session)
                                    # Note: We rely on the outer try/finally to clean up the session
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
            await self.message_repo.save_message(
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
