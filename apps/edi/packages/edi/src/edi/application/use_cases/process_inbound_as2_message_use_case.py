"""
As2ReceiverService — Application Use Case for inbound AS2 message processing.

Orchestrates the entire inbound AS2 flow strictly through domain models, domain
services, and outbound ports. No adapter-layer imports are permitted here.

Dependency Inversion is enforced via constructor injection:
  - CryptoServicePort  →  edi.adapters.outbound.security.smime_crypto_service
  - ControlPlaneUnitOfWorkPort  →  database adapter
  - DataPlaneUnitOfWorkFactoryPort  →  database adapter
  - SecretStorePort  →  AWS Secrets Manager adapter
"""

import email
import functools
import re
from email import policy
from typing import Any

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork import SystemIdPrefix, generate_id

from edi.application.dto import ProcessInboundAs2Command
from edi.domain.constants import EdiConnectionType, TransactionDirection, TransactionStatus
from edi.domain.models.as2 import (
    AS2Message,
    AS2PartnerDomainModel,
    AS2PartnershipDomainModel,
    MDNResponse,
)
from edi.domain.services.as2_protocol import (
    build_mdn,
    calculate_mic,
    parse_as2_request,
)
from edi.ports.outbound.crypto_service_port import CryptoServicePort
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from edi.ports.outbound.uow_factory import DataPlaneUnitOfWorkFactoryPort

logger = structlog.get_logger(__name__)


class ProcessInboundAs2MessageUseCase:
    """
    Application Service (Use Case Layer) for handling inbound AS2 messages.

    Follows Single Responsibility Principle: orchestrates the AS2 receive flow
    by coordinating domain services and outbound ports.

    Architecture:
      - Depends ONLY on domain models/services and outbound port abstractions.
      - Contains ZERO imports from edi.adapters.*.
    """

    def __init__(
        self,
        control_plane_uow: ControlPlaneUnitOfWorkPort,
        dp_factory: DataPlaneUnitOfWorkFactoryPort,
        secret_store: SecretStorePort,
        crypto_service: CryptoServicePort,
    ):
        self.control_plane_uow = control_plane_uow
        self.dp_factory = dp_factory
        self.secret_store = secret_store
        self.crypto_service = crypto_service

    async def process_inbound_message(
        self, command: ProcessInboundAs2Command
    ) -> tuple[bytes, dict[str, str]]:
        """
        Orchestrates the entire inbound AS2 flow:
          1. Parse HTTP Request → domain AS2Message
          2. Lookup Partnership in Control Plane
          3. Retrieve cryptographic keys from Vault
          4. Cryptographic Pipeline (Decrypt → Verify)
          5. Extract pure EDI bytes
          6. Save to Data Plane (multi-tenant)
          7. Generate MDN Response

        Returns:
            (mdn_body_bytes, mdn_headers_dict)
        """
        # 1. Parse Request
        as2_msg = self._parse_request(command.headers, command.body_bytes)
        logger.info(
            "as2_inbound_received",
            as2_from=as2_msg.as2_from,
            as2_to=as2_msg.as2_to,
        )

        # 2. Lookup Partnership
        partnership, local_partner, remote_partner = await self._lookup_partnership(
            as2_msg.as2_from, as2_msg.as2_to
        )

        # 3. Retrieve Keys
        local_priv_key, local_cert, remote_cert = await self._retrieve_keys(
            local_partner, remote_partner
        )

        # 4. Cryptographic Pipeline (Unbox)
        final_payload, mic = self._unbox_payload(
            as2_msg, command.headers, local_priv_key, local_cert, remote_cert
        )

        # 5. Extract Pure EDI
        pure_edi_bytes = self._extract_pure_edi(final_payload)

        # 6. Save to DB
        await self._save_transaction(
            partnership=partnership, as2_msg=as2_msg, pure_edi_bytes=pure_edi_bytes
        )

        # 7. Generate MDN
        disposition = "automatic-action/MDN-sent-automatically; processed"

        sign_fn = None
        requires_signed = any(
            k.lower() == "disposition-notification-options" for k in as2_msg.headers
        )
        if requires_signed:
            local_priv, local_cert_again, _ = await self._retrieve_keys(
                local_partner=local_partner, remote_partner=remote_partner
            )
            if local_priv and local_cert_again:
                sign_fn = functools.partial(
                    self.crypto_service.sign,
                    private_key_pem=local_priv,
                    public_cert_pem=local_cert_again,
                    algorithm=partnership.signature_algorithm or "sha256",
                )

        mdn: MDNResponse = build_mdn(
            as2_to=as2_msg.as2_to,
            as2_from=as2_msg.as2_from,
            message_id=as2_msg.message_id,
            disposition=disposition,
            mic=mic,
            sign_fn=sign_fn,
        )

        return mdn.body, mdn.headers

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _parse_request(self, headers: dict[str, str], body_bytes: bytes) -> AS2Message:
        try:
            return parse_as2_request(headers, body_bytes)
        except ValueError as e:
            logger.warning("as2_parse_failed", error=str(e))
            raise ValueError(f"Bad Request: {e}") from e

    async def _lookup_partnership(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel]:
        async with self.control_plane_uow:
            match = await self.control_plane_uow.as2_partnerships.get_partnership_by_as2_ids(
                as2_from=as2_from, as2_to=as2_to
            )
            if not match:
                logger.error(
                    "as2_partnership_not_found",
                    as2_from=as2_from,
                    as2_to=as2_to,
                )
                raise ValueError("Partnership not configured")
            return match

    async def _retrieve_keys(
        self, local_partner: AS2PartnerDomainModel, remote_partner: AS2PartnerDomainModel
    ) -> tuple[bytes | None, bytes | None, bytes | None]:
        local_priv_key = None
        local_cert = None
        remote_cert = None

        if local_partner.private_key_vault_ref:
            local_priv_key = await self.secret_store.retrieve_secret(
                local_partner.private_key_vault_ref
            )
        if local_partner.public_cert_vault_ref:
            local_cert = await self.secret_store.retrieve_secret(
                local_partner.public_cert_vault_ref
            )
        elif local_partner.public_cert_pem:
            local_cert = local_partner.public_cert_pem.encode()

        if remote_partner.public_cert_vault_ref:
            remote_cert = await self.secret_store.retrieve_secret(
                remote_partner.public_cert_vault_ref
            )
        elif remote_partner.public_cert_pem:
            remote_cert = remote_partner.public_cert_pem.encode()

        if not local_priv_key:
            logger.warning("as2_local_private_key_missing_skipping_decryption")

        return local_priv_key, local_cert, remote_cert

    def _unbox_payload(
        self,
        as2_msg: AS2Message,
        original_headers: dict[str, str],
        local_priv_key: bytes | None,
        local_cert: bytes | None,
        remote_cert: bytes | None,
    ) -> tuple[bytes, str | None]:
        """
        Executes the cryptographic pipeline sequentially: Decrypt → Re-evaluate → Verify → MIC.
        All crypto is delegated to self.crypto_service (CryptoServicePort).
        """
        current_entity = as2_msg.payload
        is_encrypted = as2_msg.is_encrypted
        is_signed = as2_msg.is_signed

        # Decryption Step
        if is_encrypted:
            if not local_priv_key:
                raise ValueError("Message is encrypted but local private key is missing.")
            current_entity = self._decrypt_entity(
                current_entity, original_headers, local_priv_key, local_cert
            )

            if not is_signed:
                # Re-evaluate signing status on decrypted inner payload
                parsed_inner = email.message_from_bytes(current_entity, policy=policy.HTTP)
                inner_ct = parsed_inner.get_content_type()
                if inner_ct in ("multipart/signed", "application/pkcs7-signature"):
                    is_signed = True

        # Verification Step
        mic = None
        if is_signed:
            if not remote_cert:
                raise ValueError("Message is signed but remote public certificate is missing.")
            if not is_encrypted:
                verify_entity = self._reconstruct_smime_headers(original_headers) + current_entity
            else:
                verify_entity = current_entity

            mic, raw_signed_content = self._verify_and_calculate_mic(
                verify_entity, remote_cert, as2_msg.message_id
            )
            current_entity = raw_signed_content
        else:
            mic = calculate_mic(current_entity, "sha256")
            logger.info(
                "as2_mic_calculated_unsigned",
                message_id=as2_msg.message_id,
                mic=mic,
            )

        return current_entity, mic

    def _decrypt_entity(
        self,
        current_entity: bytes,
        original_headers: dict[str, str],
        priv_key: bytes,
        cert: bytes | None,
    ) -> bytes:
        try:
            decrypted = self.crypto_service.decrypt(
                current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert or b"",
            )
            if decrypted:
                return decrypted
        except Exception as e:  # noqa: BLE001
            logger.debug("as2_decrypt_initial_attempt_failed_trying_fallback", error=str(e))

        # Fallback: prepend reconstructed S/MIME headers before retrying
        smime_headers = self._reconstruct_smime_headers(original_headers)
        try:
            decrypted = self.crypto_service.decrypt(
                smime_headers + current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert or b"",
            )
            if decrypted:
                return decrypted
            raise ValueError("Decryption returned empty result")
        except Exception as e:
            logger.exception("as2_decryption_failed_after_fallback")
            raise ValueError(f"Decryption failed: {e}") from e

    def _reconstruct_smime_headers(self, headers: dict[str, str]) -> bytes:
        smime_headers = ""
        has_cte = False
        for header_name in ["content-type", "content-transfer-encoding", "content-disposition"]:
            if header_name in headers:
                if header_name == "content-transfer-encoding":
                    has_cte = True
                smime_headers += f"{header_name.title()}: {headers[header_name]}\r\n"
        if not has_cte:
            smime_headers += "Content-Transfer-Encoding: binary\r\n"
        smime_headers += "\r\n"
        return smime_headers.encode("latin-1")

    def _verify_and_calculate_mic(
        self, verify_entity: bytes, remote_cert: bytes, message_id: str
    ) -> tuple[str, bytes]:
        msg = email.message_from_bytes(verify_entity, policy=policy.HTTP)
        boundary = msg.get_boundary()

        mic = None
        if boundary:
            boundary_bytes = b"--" + boundary.encode("ascii")
            pattern = re.compile(b"(?:\r\n|\n)" + re.escape(boundary_bytes) + b"(?:\r\n|\n|--)")
            parts = pattern.split(verify_entity)
            if len(parts) >= 3:
                raw_signed_content = parts[1]
                mic = calculate_mic(raw_signed_content, "sha256")
            else:
                mic = calculate_mic(verify_entity, "sha256")
        else:
            mic = calculate_mic(verify_entity, "sha256")

        logger.info(
            "as2_mic_calculated_signed",
            message_id=message_id,
            mic=mic,
        )

        try:
            is_valid, verified_payload = self.crypto_service.verify_signature(
                verify_entity, public_cert_pem=remote_cert
            )
            if not is_valid:
                raise ValueError("Signature verification mathematically failed")
            return mic, verified_payload
        except Exception as e:
            logger.exception("as2_signature_verification_failed")
            raise ValueError(f"Signature verification failed: {e}") from e

    def _extract_pure_edi(self, final_payload_bytes: bytes | Any) -> bytes:
        if not isinstance(final_payload_bytes, bytes):
            if hasattr(final_payload_bytes, "as_bytes"):
                final_payload_bytes = final_payload_bytes.as_bytes()
            elif isinstance(final_payload_bytes, str):
                final_payload_bytes = final_payload_bytes.encode("utf-8")

        parsed_msg = email.message_from_bytes(final_payload_bytes, policy=policy.HTTP)
        if "content-type" in parsed_msg:
            decoded_payload = parsed_msg.get_payload(decode=True)  # type: ignore[arg-type]
            if decoded_payload is not None and isinstance(decoded_payload, bytes):
                return decoded_payload
            return parsed_msg.as_bytes()
        return final_payload_bytes

    def _extract_isa_headers(self, pure_edi_bytes: bytes) -> tuple[str, str, str | None]:
        """
        Lightweight ISA parser to extract Sender and Receiver for routing
        without parsing the entire EDI structure.
        """
        content = pure_edi_bytes.decode("ascii", errors="ignore")
        if not content.startswith("ISA"):
            raise ValueError("Payload does not begin with ISA segment")

        element_separator = content[3]
        isa_segment = content[:106]
        elements = isa_segment.split(element_separator)

        if len(elements) < 9:
            raise ValueError("Malformed ISA segment")

        isa_sender = elements[6].strip()
        isa_receiver = elements[8].strip()

        st_match = re.search(rf"ST\{element_separator}(.*?)\{element_separator}", content)
        transaction_type = st_match.group(1).strip() if st_match else None

        return isa_sender, isa_receiver, transaction_type

    async def _save_transaction(
        self, partnership: AS2PartnershipDomainModel, as2_msg: AS2Message, pure_edi_bytes: bytes
    ) -> str:
        # 1. Payload-Based Routing (ISA Extraction)
        try:
            isa_sender, isa_receiver, _transaction_type = self._extract_isa_headers(pure_edi_bytes)
        except Exception as e:
            logger.exception("as2_isa_header_extraction_failed")
            raise ValueError("Invalid EDI payload for routing") from e

        # 2. Query Global DB for the actual Tenant using ISA headers
        true_tenant_id: str | None = await self.control_plane_uow.inbound_routes.get_tenant_by_isa(
            isa_sender, isa_receiver
        )
        if not true_tenant_id and partnership.tenant_id is not None:
            true_tenant_id = str(partnership.tenant_id)

        from identity.domain.identity_context import PLATFORM_TENANT_ID

        if not true_tenant_id or true_tenant_id == PLATFORM_TENANT_ID:
            logger.error(
                "as2_tenant_resolution_failed",
                isa_sender=isa_sender,
                isa_receiver=isa_receiver,
            )
            raise ValueError("No tenant could be identified for this ISA pair")

        logger.info(
            "as2_transaction_saving",
            isa_sender=isa_sender,
            isa_receiver=isa_receiver,
            true_tenant_id=true_tenant_id,
        )

        edi_record = {
            "trace_id": generate_id(SystemIdPrefix.GENERIC),
            "direction": TransactionDirection.INBOUND.value,
            "connection_type": EdiConnectionType.AS2.value,
            "sender_id": isa_sender,
            "receiver_id": isa_receiver,
            "as2_sender_id": as2_msg.as2_from,
            "as2_receiver_id": as2_msg.as2_to,
            "message_id": as2_msg.message_id,
            "mdn_mode": partnership.mdn_type,
            "signature_algorithm": partnership.signature_algorithm,
            "encryption_algorithm": partnership.encryption_algorithm,
            "edi_data": pure_edi_bytes,
            "status": TransactionStatus.RECEIVED.value,
        }

        # 3. Save to the true Tenant's Data Plane Shard via factory
        async with self.dp_factory.get_data_plane_uow(true_tenant_id, "edi") as dp_uow:
            import os

            from edi.domain.constants import EDI_MESSAGE_ID_PREFIX
            from edi.domain.events import TransformRequestedEvent
            from edi.domain.models.base import Direction, RecordStatus
            from edi.domain.models.transactions import EdiMessageDomainModel

            edi_message_aggregate = EdiMessageDomainModel(
                id=f"{EDI_MESSAGE_ID_PREFIX}_{os.urandom(12).hex()}",
                tenant_id=true_tenant_id,
                trace_id=str(edi_record["trace_id"]),
                direction=Direction(str(edi_record["direction"])),
                connection_type=str(edi_record["connection_type"])
                if edi_record.get("connection_type")
                else None,
                sender_id=str(edi_record["sender_id"]) if edi_record.get("sender_id") else None,
                receiver_id=str(edi_record["receiver_id"])
                if edi_record.get("receiver_id")
                else None,
                as2_sender_id=str(edi_record["as2_sender_id"])
                if edi_record.get("as2_sender_id")
                else None,
                as2_receiver_id=str(edi_record["as2_receiver_id"])
                if edi_record.get("as2_receiver_id")
                else None,
                message_id=str(edi_record["message_id"]) if edi_record.get("message_id") else None,
                mdn_mode=str(edi_record["mdn_mode"]) if edi_record.get("mdn_mode") else None,
                signature_algorithm=str(edi_record["signature_algorithm"])
                if edi_record.get("signature_algorithm")
                else None,
                encryption_algorithm=str(edi_record["encryption_algorithm"])
                if edi_record.get("encryption_algorithm")
                else None,
                edi_data=pure_edi_bytes.decode("utf-8", errors="ignore"),
                status=RecordStatus(str(edi_record["status"])),
            )

            msg_id = await dp_uow.transactions.create_edi_message(
                tenant_id=true_tenant_id,
                payload={
                    "id": edi_message_aggregate.id,
                    "trace_id": edi_message_aggregate.trace_id,
                    "direction": edi_message_aggregate.direction,
                    "connection_type": edi_message_aggregate.connection_type,
                    "sender_id": edi_message_aggregate.sender_id,
                    "receiver_id": edi_message_aggregate.receiver_id,
                    "as2_sender_id": edi_message_aggregate.as2_sender_id,
                    "as2_receiver_id": edi_message_aggregate.as2_receiver_id,
                    "message_id": edi_message_aggregate.message_id,
                    "mdn_mode": edi_message_aggregate.mdn_mode,
                    "signature_algorithm": edi_message_aggregate.signature_algorithm,
                    "encryption_algorithm": edi_message_aggregate.encryption_algorithm,
                    "edi_data": edi_message_aggregate.edi_data,
                    "status": edi_message_aggregate.status,
                },
            )

            outbox_payload = TransformRequestedEvent(
                trace_id=str(edi_record["trace_id"]),
                tenant_id=true_tenant_id,
                edi_message_id=str(msg_id),
                sender_id=isa_sender,
                receiver_id=isa_receiver,
                status=TransactionStatus.RECEIVED.value,
                explicit_idempotency_key=str(msg_id),
            )

            edi_message_aggregate.add_domain_event(outbox_payload)

            await dp_uow.transactions.save(edi_message_aggregate)

            await dp_uow.commit()

            return str(msg_id)
