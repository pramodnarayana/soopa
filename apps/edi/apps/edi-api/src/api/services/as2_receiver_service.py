import email
import logging
import re
import uuid
from email import policy
from typing import Any

from as2_core.mdn import build_mdn, calculate_mic
from as2_core.message import AS2Message
from as2_core.parser import parse_as2_request
from database.models.control_plane import DatabaseShard, Tenant, TenantShard
from domain.events import PipelineEventType
from security.smime import decrypt_payload, verify_signature
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.uow import ControlPlaneUnitOfWork
from api.ports.vault import VaultPort

logger = logging.getLogger(__name__)


class As2ReceiverService:
    """
    Application Service (Use Case Layer) for handling inbound AS2 messages.
    Strictly follows Single Responsibility Principle and encapsulates business logic.
    """

    def __init__(self, global_session: AsyncSession, vault: VaultPort, db_router: Any):
        self.global_session = global_session
        self.vault = vault
        self.db_router = db_router
        self.control_plane_uow = ControlPlaneUnitOfWork(global_session=global_session)

    async def process_inbound_message(
        self, headers: dict[str, str], body_bytes: bytes
    ) -> tuple[bytes, dict[str, str]]:
        """
        Orchestrates the entire inbound AS2 flow:
        1. Parse HTTP Request
        2. Lookup Partnership
        3. Retrieve Keys
        4. Cryptographic Pipeline (Decrypt -> Verify)
        5. Save to Data Plane (Multi-Tenant)
        6. Generate MDN Response

        Returns: (MDN Body Bytes, MDN Headers Dict)
        """
        # 1. Parse Request
        as2_msg = self._parse_request(headers, body_bytes)
        logger.info(f"Looking up partnership: from '{as2_msg.as2_from}' to '{as2_msg.as2_to}'")

        # 2. Lookup Partnership
        partnership, local_partner, remote_partner = await self._lookup_partnership(
            as2_msg.as2_from, as2_msg.as2_to
        )

        # 3. Retrieve Keys
        local_priv_key, local_cert, remote_cert = self._retrieve_keys(local_partner, remote_partner)

        # 4. Cryptographic Pipeline (Unbox)
        final_payload, mic = self._unbox_payload(
            as2_msg, headers, local_priv_key, local_cert, remote_cert
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
            local_priv, local_cert, _ = self._retrieve_keys(
                local_partner=local_partner, remote_partner=remote_partner
            )
            if local_priv and local_cert:
                import functools

                from security.smime import sign_payload

                sign_fn = functools.partial(
                    sign_payload,
                    private_key_pem=local_priv,
                    public_cert_pem=local_cert,
                    algorithm=partnership.signature_algorithm or "sha256",
                )

        mdn = build_mdn(
            as2_to=as2_msg.as2_to,
            as2_from=as2_msg.as2_from,
            message_id=as2_msg.message_id,
            disposition=disposition,
            mic=mic,
            sign_fn=sign_fn,
        )

        return mdn.body, mdn.headers

    def _parse_request(self, headers: dict[str, str], body_bytes: bytes) -> AS2Message:
        try:
            return parse_as2_request(headers, body_bytes)
        except ValueError as e:
            logger.warning(f"Failed to parse AS2 request: {e}")
            raise ValueError(f"Bad Request: {e}") from e

    async def _lookup_partnership(self, as2_from: str, as2_to: str):  # type: ignore
        async with self.control_plane_uow:
            match = await self.control_plane_uow.as2_partnerships.get_partnership_by_as2_ids(
                as2_from=as2_from, as2_to=as2_to
            )
            if not match:
                logger.error(f"Partnership not found in Control Plane for {as2_from} -> {as2_to}")
                raise ValueError("Partnership not configured")
            return match

    def _retrieve_keys(  # type: ignore
        self, local_partner, remote_partner
    ) -> tuple[bytes | None, bytes | None, bytes | None]:
        local_priv_key = None
        local_cert = None
        remote_cert = None

        if local_partner.private_key_vault_ref:
            local_priv_key = self.vault.retrieve_secret(local_partner.private_key_vault_ref)
        if local_partner.public_cert_vault_ref:
            local_cert = self.vault.retrieve_secret(local_partner.public_cert_vault_ref)
        elif local_partner.public_cert_pem:
            local_cert = local_partner.public_cert_pem.encode()

        if remote_partner.public_cert_vault_ref:
            remote_cert = self.vault.retrieve_secret(remote_partner.public_cert_vault_ref)
        elif remote_partner.public_cert_pem:
            remote_cert = remote_partner.public_cert_pem.encode()

        if not local_priv_key:
            logger.warning("Local private key not configured — skipping decryption")

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
        Executes the cryptographic pipeline sequentially: Decrypt -> Re-evaluate Sign -> Verify -> MIC.
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
            logger.info(f"Calculated MIC (sha256) for unsigned message {as2_msg.message_id}: {mic}")

        return current_entity, mic

    def _decrypt_entity(
        self,
        current_entity: bytes,
        original_headers: dict[str, str],
        priv_key: bytes,
        cert: bytes | None,
    ) -> bytes:
        try:
            decrypted = decrypt_payload(
                current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert,  # type: ignore
            )
            if decrypted:
                return decrypted
        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.debug(f"Initial decryption attempt failed (will try fallback): {e}")
            pass

        # Fallback to prepending headers for openssl parsing
        smime_headers = self._reconstruct_smime_headers(original_headers)
        try:
            decrypted = decrypt_payload(
                smime_headers + current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert,  # type: ignore
            )
            if decrypted:
                return decrypted
            raise ValueError("Decryption returned empty")
        except Exception as e:
            logger.error(f"Decryption failed after fallback: {e}")
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

        logger.info(f"Calculated MIC (sha256) for signed message {message_id}: {mic}")

        try:
            is_valid, verified_payload = verify_signature(
                verify_entity, public_cert_pem=remote_cert
            )
            if not is_valid:
                raise ValueError("Signature verification mathematically failed")
            return mic, verified_payload
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            raise ValueError(f"Signature verification failed: {e}") from e

    def _extract_pure_edi(self, final_payload_bytes: bytes | str | Any) -> bytes:
        if not isinstance(final_payload_bytes, bytes):
            final_payload_bytes = final_payload_bytes.as_bytes()  # type: ignore

        parsed_msg = email.message_from_bytes(final_payload_bytes, policy=policy.HTTP)
        if "content-type" in parsed_msg:
            decoded_payload = parsed_msg.get_payload(decode=True)
            if decoded_payload is not None:
                return decoded_payload  # type: ignore
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

        # Attempt to find ST segment to extract transaction type
        import re

        st_match = re.search(rf"ST\{element_separator}(.*?)\{element_separator}", content)
        transaction_type = st_match.group(1).strip() if st_match else None

        return isa_sender, isa_receiver, transaction_type

    async def _save_transaction(  # type: ignore
        self, partnership, as2_msg: AS2Message, pure_edi_bytes: bytes
    ) -> str:

        # 1. Payload-Based Routing (ISA Extraction)
        # We MUST extract ISA headers here because if the AS2 Partnership is global (tenant_id = 0),
        # we need to find the true tenant ID by looking up the inbound route.
        try:
            isa_sender, isa_receiver, transaction_type = self._extract_isa_headers(pure_edi_bytes)
        except Exception as e:
            logger.error(f"Failed to extract ISA headers: {e}")
            raise ValueError("Invalid EDI payload for routing") from e

        # 2. Query Global DB for the actual Tenant using ISA headers
        true_tenant_id: str | None = await self.control_plane_uow.inbound_routes.get_tenant_by_isa(
            isa_sender, isa_receiver
        )
        if not true_tenant_id and partnership.tenant_id is not None:
            true_tenant_id = str(partnership.tenant_id)

        if not true_tenant_id or true_tenant_id == "0":
            logger.error(
                f"Cannot save payload. No tenant could be identified for ISA {isa_sender} -> {isa_receiver}"
            )
            raise ValueError("No tenant could be identified for this ISA pair")

        logger.info(f"Saved AS2 payload ({isa_sender}->{isa_receiver}) to Tenant {true_tenant_id}")

        edi_record = {
            "trace_id": uuid.uuid4(),
            "direction": "INBOUND",
            "connection_type": "AS2",
            "sender_id": isa_sender,
            "receiver_id": isa_receiver,
            "as2_sender_id": as2_msg.as2_from,
            "as2_receiver_id": as2_msg.as2_to,
            "message_id": as2_msg.message_id,
            "mdn_mode": partnership.mdn_type,
            "signature_algorithm": partnership.signature_algorithm,
            "encryption_algorithm": partnership.encryption_algorithm,
            "edi_data": pure_edi_bytes,
            "status": "RECEIVED",
        }

        # 3. Save directly to the true Tenant's Data Plane Shard
        stmt = (
            select(Tenant, DatabaseShard)
            .join(TenantShard, Tenant.id == TenantShard.tenant_id)
            .join(DatabaseShard, TenantShard.shard_id == DatabaseShard.id)
            .where(Tenant.id == true_tenant_id)
        )
        result = await self.global_session.execute(stmt)
        row = result.first()
        if not row:
            logger.error(f"Tenant {true_tenant_id} not found in global DB")
            raise ValueError("Tenant routing failed")

        tenant, shard = row
        async_gen_tenant = self.db_router.get_tenant_session(true_tenant_id, shard.name, shard.dsn)
        tenant_session = await anext(async_gen_tenant)
        try:
            from api.adapters.outbox_repository import SqlAlchemyDataPlaneOutboxRepository
            from api.adapters.transaction_repository import SqlAlchemyTransactionRepository

            dp_repo = SqlAlchemyTransactionRepository(tenant_session)
            outbox_repo = SqlAlchemyDataPlaneOutboxRepository(tenant_session)
            msg_id = await dp_repo.create_edi_message(tenant_id=true_tenant_id, payload=edi_record)

            outbox_payload = {
                "edi_message_id": str(msg_id),
                "trace_id": str(edi_record["trace_id"]),
                "sender_id": isa_sender,
                "receiver_id": isa_receiver,
                "status": "RECEIVED",
            }
            await outbox_repo.publish_outbox_event(
                tenant_id=true_tenant_id,
                event_type=PipelineEventType.TRANSFORM_EVENT,
                payload=outbox_payload,
                idempotency_key=msg_id,
            )

            await tenant_session.commit()

            return str(msg_id)
        finally:
            await async_gen_tenant.aclose()
