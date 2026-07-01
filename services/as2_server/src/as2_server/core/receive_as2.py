import time
import uuid

from as2_core import (
    AS2MDN,
    AS2Message,
    Disposition,
    generate_mdn,
)
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
    ) -> None:
        self.tenant_repo = tenant_repo
        self.partner_repo = partner_repo
        self.message_repo = message_repo
        self.storage = storage
        self.vault = vault
        self.tracer = ObservabilityProvider.tracer()
        self.metrics = ObservabilityProvider.metrics()
        self.logger = ObservabilityProvider.logger(__name__)

    async def execute(self, as2_msg: AS2Message) -> AS2MDN:
        start_time = time.perf_counter()

        tenant_id = None
        try:
            tenant_id = await self.tenant_repo.resolve_tenant_id(as2_msg.as2_to)
        except ValueError as e:
            self.logger.warning("tenant_resolution_ambiguous", error=str(e), as2_to=as2_msg.as2_to)
        except Exception as e:
            self.logger.warning("tenant_resolution_failed", error=str(e), as2_to=as2_msg.as2_to)

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

        with self.tracer.start_span("as2.s3_upload"):
            as2_msg.payload = processed_payload
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
                s3_key=storage_uri,
                status=status,
                as2_message_id=as2_msg.message_id,
            )

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
