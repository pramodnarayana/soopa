import contextlib
import typing

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork.id_registry import SystemIdPrefix
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
        uow_factory: typing.Callable[
            [], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]
        ],
        as2_delivery: AS2DeliveryPort,
        vault: SecretStorePort | None = None,
    ) -> None:
        super().__init__(uow_factory, vault)
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
            logger.error(
                "as2_delivery_http_failed",
                trace_id=trace_id,
                status_code=status_code,
            )
            # Transient error, raise so outbox can retry if applicable
            raise RuntimeError(f"AS2 Delivery failed with HTTP {status_code}")

        try:
            mdn = parse_mdn(response_headers, response_body)
        except Exception as e:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
                await self._emit_delivery_completed(uow, trace_id, direction, MessageStatus.FAILED)
                await uow.commit()
            logger.exception(
                "AS2 MDN parsing or processing failed for trace_id={trace_id}", trace_id=trace_id
            )
            raise ValueError(f"AS2 MDN parsing or processing failed: {e}") from e

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
                            "as2_mdn_mic_mismatch",
                            trace_id=trace_id,
                            expected_mic=as2_msg.mic,
                            received_mic=received_mic,
                        )

        if is_success:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_edi_message_status(trace_id, MessageStatus.DELIVERED)
                await self._emit_delivery_completed(
                    uow, trace_id, direction, MessageStatus.DELIVERED
                )
                await uow.commit()
            logger.info(
                "as2_delivery_succeeded",
                trace_id=trace_id,
                status_code=status_code,
                mic=as2_msg.mic,
            )
            return

        async with self.uow_factory() as uow, uow:
            await uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
            await self._emit_delivery_completed(uow, trace_id, direction, MessageStatus.FAILED)
            await uow.commit()

        logger.error(
            "as2_mdn_failure",
            trace_id=trace_id,
            disposition=disposition,
            received_mic=received_mic,
            expected_mic=as2_msg.mic,
        )
        raise ValueError(f"Sync MDN indicates failure: {disposition}")

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_msg: EdiMessageDomainModel,
        idempotency_key: str | None = None,
    ) -> None:
        try:
            async with self.uow_factory() as uow, uow:
                partnerships = await uow.as2_partnerships.get_as2_partnerships_by_remote_partner_id(
                    edi_msg.tenant_id, partner_id, active=True
                )
                if not partnerships:
                    raise ValueError(
                        f"No active AS2 partnership found for remote partner {partner_id}."
                    )

                if len(partnerships) != 1:
                    logger.error(
                        "multiple_active_as2_partnerships_found_for_remote_partner",
                        tenant_id=edi_msg.tenant_id,
                        remote_partner_id=partner_id,
                    )
                    raise ValueError(
                        f"Expected exactly 1 active AS2 partnership for remote partner {partner_id}, found {len(partnerships)}."
                    )

                partnership_dto = partnerships[0]

                remote_partner_dto = await uow.as2_partners.get_as2_partner(
                    edi_msg.tenant_id, partnership_dto.remote_partner_id
                )
                if not remote_partner_dto:
                    raise ValueError("AS2 remote partner not found.")

                remote_url: str | None = remote_partner_dto.url
                if not remote_url:
                    raise ValueError(f"AS2 partner {partner_id} has no remote_url configured.")

                local_partner_id: str | None = partnership_dto.local_partner_id
                local_partner_dto = (
                    await uow.as2_partners.get_as2_partner(edi_msg.tenant_id, local_partner_id)
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
        except ValueError:
            async with self.uow_factory() as uow, uow:
                await uow.transactions.update_edi_message_status(trace_id, MessageStatus.FAILED)
                await self._emit_delivery_completed(
                    uow, trace_id, edi_msg.direction, MessageStatus.FAILED
                )
                await uow.commit()
            logger.exception(
                "as2_message_build_terminal_failure",
                trace_id=trace_id,
                partner_id=partner_id,
            )
            raise
        except Exception:
            logger.exception(
                "as2_message_build_transient_failure",
                trace_id=trace_id,
                partner_id=partner_id,
            )
            raise

        try:
            status_code, response_headers, response_body = await self.as2_delivery.deliver(
                url=remote_url,
                body=as2_msg.body,
                headers=as2_msg.headers,
            )
        except Exception as e:
            logger.exception(
                "as2_http_transmission_failed",
                trace_id=trace_id,
                remote_url=remote_url,
            )
            raise RuntimeError(f"AS2 transmission error: {e}") from e

        await self._process_mdn_response(
            trace_id, edi_msg.direction, as2_msg, status_code, response_headers, response_body
        )
