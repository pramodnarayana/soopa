import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id

from edi.application.dtos.partners import AS2PartnershipDTO, LocalAS2PartnerDTO, RemoteAS2PartnerDTO
from edi.core.pipeline.as2_orchestrator import AS2MessageOrchestrator
from edi.core.pipeline.delivery.base import BaseDeliveryStrategy
from edi.domain.enums import MessageStatus
from edi.domain.models.as2 import OutboundAS2Message
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.services.as2_protocol import parse_mdn
from edi.ports.outbound.as2_delivery_port import AS2DeliveryPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class As2DeliveryStrategy(BaseDeliveryStrategy):
    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        as2_delivery: AS2DeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow, vault)
        self.as2_delivery = as2_delivery
        self._as2_orchestrator = AS2MessageOrchestrator(vault=vault)

    async def _process_mdn_response(
        self,
        trace_id: str,
        direction: str,
        as2_msg: OutboundAS2Message,
        status_code: int,
        response_headers: dict[str, str],
        response_body: bytes,
    ) -> None:
        if not (200 <= status_code < 300):
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
            logger.error(
                "AS2 Delivery failed for trace_id={trace_id}. "
                "HTTP status: {status_code}, body: {response_body!r}"
            )
            raise RuntimeError(f"AS2 Delivery failed with HTTP {status_code}")

        try:
            mdn = parse_mdn(response_headers, response_body)
        except Exception as e:
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 MDN parsing or processing failed for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError(f"AS2 MDN parsing or processing failed: {e}") from e

        disposition = mdn.disposition
        received_mic = mdn.mic

        is_success = False
        if disposition:
            disp_parts = disposition.split(";", 1)
            if len(disp_parts) == 2:
                status_part = disp_parts[1].strip().lower()
                if (
                    status_part.startswith("processed")
                    and "error" not in status_part
                    and "failed" not in status_part
                ):
                    is_success = True
                    if as2_msg.mic and (
                        not received_mic
                        or as2_msg.mic.replace(" ", "") != received_mic.replace(" ", "")
                    ):
                        is_success = False
                        logger.warning(
                            "MDN MIC mismatch for trace_id={trace_id}. "
                            "Expected {as2_msg.mic}, got {received_mic}"
                        )

        if is_success:
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
            await self._emit_delivery_completed(trace_id, direction, MessageStatus.DELIVERED)
            logger.info(
                "Delivered trace_id={trace_id} (HTTP {status_code}). MIC={as2_msg.mic}",
                trace_id=trace_id,
                status_code=status_code,
                as2_msg_mic=as2_msg.mic,
            )
            return

        await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
        await self._emit_delivery_completed(trace_id, direction, MessageStatus.FAILED)
        logger.error(
            "Sync MDN indicates failure for trace_id={trace_id}. "
            "Disposition: {disposition!r}, Received-MIC: {received_mic!r}, Expected-MIC: {as2_msg.mic!r}"
        )
        raise RuntimeError(f"Sync MDN indicates failure: {disposition}")

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        if not await self.uow.transactions.claim_edi_message(trace_id):
            logger.warning(
                "Could not claim trace_id={trace_id} (already claimed or terminal).",
                trace_id=trace_id,
            )
            return

        try:
            partnership_dto = await self.uow.as2_partnerships.get_as2_partnership(
                edi_msg.tenant_id, partner_id
            )
            if not partnership_dto:
                raise ValueError(f"AS2 partnership {partner_id} not found.")

            remote_partner_dto = await self.uow.as2_partners.get_as2_partner(
                edi_msg.tenant_id, partnership_dto.remote_partner_id
            )
            if not remote_partner_dto:
                raise ValueError("AS2 remote partner not found.")

            remote_url: str | None = remote_partner_dto.url
            if not remote_url:
                raise ValueError(f"AS2 partner {partner_id} has no remote_url configured.")

            local_partner_id: str | None = partnership_dto.local_partner_id
            local_partner_dto = (
                await self.uow.as2_partners.get_as2_partner(edi_msg.tenant_id, local_partner_id)
                if local_partner_id
                else None
            )

            if not edi_msg.edi_data:
                raise ValueError("Empty EDI data")
            raw_payload = edi_msg.edi_data.encode("utf-8")

            # Map DomainModels to DTOs for the Orchestrator
            remote_dto = RemoteAS2PartnerDTO(
                id=remote_partner_dto.id,
                as2_id=remote_partner_dto.as2_id,
                name=remote_partner_dto.name,
                public_cert_pem=remote_partner_dto.public_cert_pem,
                public_cert_vault_ref=remote_partner_dto.public_cert_vault_ref,
                prev_public_cert_pem=remote_partner_dto.prev_public_cert_pem,
                prev_public_cert_vault_ref=remote_partner_dto.prev_public_cert_vault_ref,
                url=remote_partner_dto.url,
            )
            partnership_dto_mapped = AS2PartnershipDTO(
                id=partnership_dto.id,
                name=partnership_dto.name,
                local_partner_id=partnership_dto.local_partner_id,
                remote_partner_id=partnership_dto.remote_partner_id,
                credentials_vault_ref=partnership_dto.credentials_vault_ref,
                mdn_url=partnership_dto.mdn_url,
                mdn_type=partnership_dto.mdn_type,
                encryption_algorithm=partnership_dto.encryption_algorithm,
                signature_algorithm=partnership_dto.signature_algorithm,
                advanced_flags=partnership_dto.advanced_flags,
            )
            local_dto = None
            if local_partner_dto:
                local_dto = LocalAS2PartnerDTO(
                    id=local_partner_dto.id,
                    as2_id=local_partner_dto.as2_id,
                    name=local_partner_dto.name,
                    public_cert_pem=local_partner_dto.public_cert_pem,
                    public_cert_vault_ref=local_partner_dto.public_cert_vault_ref,
                    private_key_vault_ref=local_partner_dto.private_key_vault_ref,
                    prev_public_cert_vault_ref=local_partner_dto.prev_public_cert_vault_ref,
                    prev_private_key_vault_ref=local_partner_dto.prev_private_key_vault_ref,
                )

            as2_msg = await self._as2_orchestrator.build(
                raw_payload=raw_payload,
                local_partner=local_dto,
                remote_partner=remote_dto,
                partnership=partnership_dto_mapped,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        except Exception as e:
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 Delivery Adapter is misconfigured or failed to build for trace_id={trace_id}",
                trace_id=trace_id,
            )
            raise RuntimeError(
                "AS2 Delivery Adapter failed to build for trace_id={trace_id}"
            ) from e

        try:
            status_code, response_headers, response_body = await self.as2_delivery.deliver(
                url=remote_url,
                body=as2_msg.body,
                headers=as2_msg.headers,
            )
        except RuntimeError as e:
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 Delivery Adapter is misconfigured for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError(
                "AS2 Delivery Adapter is misconfigured for trace_id={trace_id}"
            ) from e
        except Exception as e:
            await self.uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(trace_id, edi_msg.direction, MessageStatus.FAILED)
            logger.exception(
                "AS2 HTTP transmission failed for trace_id={trace_id}", trace_id=trace_id
            )
            raise RuntimeError("AS2 HTTP transmission failed for trace_id={trace_id}") from e

        await self._process_mdn_response(
            trace_id, edi_msg.direction, as2_msg, status_code, response_headers, response_body
        )
