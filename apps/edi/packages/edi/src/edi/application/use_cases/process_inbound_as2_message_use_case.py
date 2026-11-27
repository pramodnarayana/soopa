"""As2ReceiverService — Application Use Case for inbound AS2 message processing.

Orchestrates the entire inbound AS2 flow strictly through domain models, domain
services, and outbound ports. No adapter-layer imports are permitted here.

Dependency Inversion is enforced via constructor injection:
  - CryptoServicePort  ->  edi.adapters.outbound.security.smime_crypto_service
  - ControlPlaneUnitOfWorkPort  ->  database adapter
  - DataPlaneUnitOfWorkFactoryPort  ->  database adapter
  - SecretStorePort  ->  centralized secret-store adapter

First-Class Error Handling:
  - Known AS2 protocol, cryptographic, and ISA routing rejections return
    ``Result.fail(As2InboundError)`` with structured RFC 4130 MDN disposition
    modifiers and full ISA/AS2 diagnostic context.
"""

from __future__ import annotations

import email
import functools
import json
import re
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from email import policy
from types import TracebackType
from typing import Protocol

import structlog
from secret_store.ports.secret_store_port import SecretStorePort
from seedwork import generate_id
from seedwork.domain.exceptions import Result
from seedwork.id_registry import SystemIdPrefix

from edi.domain.constants import EdiIdPrefix as DomainIdPrefix
from edi.domain.exceptions import (
    As2InboundError,
    EdiError,
    OrchestrationError,
    RouteNotActiveEdiError,
)
from edi.domain.partner.as2.messages import AS2Message, MDNResponse
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.partner.as2.protocol import build_mdn, calculate_mic, parse_as2_request
from edi.domain.routing.enums import Direction, EdiConnectionType, EdiDirection
from edi.domain.routing.isa_resolution import IsaResolutionStatus, IsaTenantResolution
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import EdiStandard, MessageStatus, RecordStatus
from edi.ports.outbound.crypto_service_port import CryptoServicePort

logger = structlog.get_logger(__name__)

_AS2_PROCESSED_DISPOSITION = "automatic-action/MDN-sent-automatically; processed"
_INITIAL_MESSAGE_STATE = "EXTRACTED"


class _PartnershipLookupPort(Protocol):
    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2Partnership, AS2Partner, AS2Partner] | None: ...


class _InboundRouteLookupPort(Protocol):
    async def resolve_tenant_by_isa(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        *,
        transaction_type: str | None = None,
    ) -> IsaTenantResolution: ...


class InboundAs2ControlPlaneUoWPort(Protocol):
    """Interface-segregated Control Plane UoW surface required by inbound AS2 ingestion."""

    @property
    def as2_partnerships(self) -> _PartnershipLookupPort: ...
    @property
    def inbound_routes(self) -> _InboundRouteLookupPort: ...

    async def __aenter__(self) -> InboundAs2ControlPlaneUoWPort: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class _EdiMessageSaverPort(Protocol):
    async def save(self, aggregate: EdiMessage) -> object: ...


class InboundAs2DataPlaneUoWPort(Protocol):
    """Interface-segregated Data Plane UoW surface required by inbound AS2 ingestion."""

    @property
    def edi_messages(self) -> _EdiMessageSaverPort: ...

    async def commit(self) -> None: ...


class InboundAs2DataPlaneFactoryPort(Protocol):
    """Interface-segregated Data Plane UoW factory for inbound AS2 ingestion."""

    def get_data_plane_uow(
        self, tenant_id: str, app_slug: str
    ) -> AbstractAsyncContextManager[InboundAs2DataPlaneUoWPort]: ...


@dataclass(frozen=True)
class ProcessInboundAs2Command:
    headers: Mapping[str, str]
    body_bytes: bytes


@dataclass(frozen=True)
class ProcessInboundAs2Result:
    mdn_body: bytes
    mdn_headers: Mapping[str, str]
    edi_message_id: str
    tenant_id: str
    isa_sender: str
    isa_receiver: str
    routing_error: EdiError | None = None


@dataclass(frozen=True)
class _ExtractedIsaMetadata:
    isa_sender: str
    isa_receiver: str
    transaction_type: str | None
    interchange_control_no: str | None


class ProcessInboundAs2MessageUseCase:
    """Application Service (Use Case Layer) for handling inbound AS2 messages.

    Follows Single Responsibility Principle: orchestrates the AS2 receive flow
    by coordinating domain services and outbound ports.

    Architecture:
      - Depends ONLY on domain models/services and outbound port abstractions.
      - Contains ZERO imports from edi.adapters.*.
    """

    def __init__(
        self,
        control_plane_uow: InboundAs2ControlPlaneUoWPort,
        dp_factory: InboundAs2DataPlaneFactoryPort,
        secret_store: SecretStorePort,
        crypto_service: CryptoServicePort,
    ) -> None:
        self.control_plane_uow = control_plane_uow
        self.dp_factory = dp_factory
        self.secret_store = secret_store
        self.crypto_service = crypto_service

    async def process_inbound_message(
        self, command: ProcessInboundAs2Command
    ) -> Result[ProcessInboundAs2Result, As2InboundError]:
        """Orchestrates the entire inbound AS2 flow and returns a first-class Result.

        Steps:
          1. Parse HTTP Request -> domain AS2Message
          2. Lookup Partnership in Control Plane
          3. Retrieve cryptographic keys from SecretStorePort
          4. Cryptographic Pipeline (Decrypt -> Verify -> MIC)
          5. Extract pure EDI bytes & ISA sender/receiver pair
          6. Resolve active tenant via ISA pair in Control Plane
          7. Generate MDN & persist EdiMessage to Tenant Data Plane
        """
        # 1. Parse Request
        parse_res = self._parse_request(command.headers, command.body_bytes)
        if parse_res.is_err:
            return Result.fail(parse_res.unwrap_err())
        as2_msg = parse_res.unwrap()

        logger.info(
            "as2_inbound_received",
            as2_from=as2_msg.as2_from,
            as2_to=as2_msg.as2_to,
            message_id=as2_msg.message_id,
        )

        # 2. Lookup Partnership
        partnership_res = await self._lookup_partnership(
            as2_from=as2_msg.as2_from,
            as2_to=as2_msg.as2_to,
            message_id=as2_msg.message_id,
        )
        if partnership_res.is_err:
            return Result.fail(partnership_res.unwrap_err())
        partnership, local_partner, remote_partner = partnership_res.unwrap()

        # 3. Retrieve Keys (once per message)
        local_priv_key, local_cert, remote_cert = await self._retrieve_keys(
            local_partner, remote_partner
        )

        # 4. Cryptographic Pipeline (Unbox)
        unbox_res = self._unbox_payload(
            as2_msg, command.headers, local_priv_key, local_cert, remote_cert
        )
        if unbox_res.is_err:
            return Result.fail(unbox_res.unwrap_err())
        final_payload, mic = unbox_res.unwrap()

        # 5. Extract Pure EDI & ISA Metadata
        pure_edi_bytes = self._extract_pure_edi(final_payload)
        isa_res = self._extract_isa_headers(
            pure_edi_bytes,
            as2_from=as2_msg.as2_from,
            as2_to=as2_msg.as2_to,
            message_id=as2_msg.message_id,
        )
        if isa_res.is_err:
            return Result.fail(isa_res.unwrap_err())
        isa_meta = isa_res.unwrap()

        # 6. Resolve tenant & route state from Control Plane using ISA pair + transaction type
        tenant_res = await self._resolve_tenant_for_isa(
            isa_sender=isa_meta.isa_sender,
            isa_receiver=isa_meta.isa_receiver,
            transaction_type=isa_meta.transaction_type,
            as2_msg=as2_msg,
        )
        if tenant_res.is_err:
            return Result.fail(tenant_res.unwrap_err())
        true_tenant_id, resolution = tenant_res.unwrap()

        # 7. Generate valid RFC 4130 processed MDN (remote TP transport succeeded;
        # internal inactive-route holds must NEVER return an error MDN to the partner)
        sign_fn = None
        requires_signed = any(
            k.lower() == "disposition-notification-options" for k in as2_msg.headers
        )
        if requires_signed and local_priv_key and local_cert:
            sign_fn = functools.partial(
                self.crypto_service.sign,
                private_key_pem=local_priv_key,
                public_cert_pem=local_cert,
                algorithm=partnership.signature_algorithm or "sha256",
            )

        mdn: MDNResponse = build_mdn(
            as2_to=as2_msg.as2_to,
            as2_from=as2_msg.as2_from,
            message_id=as2_msg.message_id,
            disposition=_AS2_PROCESSED_DISPOSITION,
            mic=mic,
            sign_fn=sign_fn,
        )

        # 8. Persist EdiMessage to Tenant Data Plane (status=RECEIVED in both active & inactive-route cases)
        routing_error: EdiError | None = (
            RouteNotActiveEdiError.for_isa_pair(
                isa_sender=isa_meta.isa_sender,
                isa_receiver=isa_meta.isa_receiver,
                inactive_route_ids=resolution.inactive_route_ids,
                inactive_route_names=resolution.inactive_route_names,
                as2_from=as2_msg.as2_from,
                as2_to=as2_msg.as2_to,
                message_id=as2_msg.message_id,
            )
            if resolution.status == IsaResolutionStatus.INACTIVE
            else None
        )

        edi_message_id = await self._save_inbound_message(
            true_tenant_id=true_tenant_id,
            isa_meta=isa_meta,
            partnership=partnership,
            remote_partner=remote_partner,
            as2_msg=as2_msg,
            pure_edi_bytes=pure_edi_bytes,
            routing_error=routing_error,
            mdn_response=mdn.body.decode("utf-8", errors="ignore") if mdn.body else None,
        )

        return Result.ok(
            ProcessInboundAs2Result(
                mdn_body=mdn.body,
                mdn_headers=mdn.headers,
                edi_message_id=edi_message_id,
                tenant_id=true_tenant_id,
                isa_sender=isa_meta.isa_sender,
                isa_receiver=isa_meta.isa_receiver,
                routing_error=routing_error,
            )
        )

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _parse_request(
        self, headers: Mapping[str, str], body_bytes: bytes
    ) -> Result[AS2Message, As2InboundError]:
        try:
            return Result.ok(parse_as2_request(headers, body_bytes))
        except ValueError as exc:
            return Result.fail(As2InboundError.parse_failed(reason=str(exc)))

    async def _lookup_partnership(
        self, *, as2_from: str, as2_to: str, message_id: str
    ) -> Result[tuple[AS2Partnership, AS2Partner, AS2Partner], As2InboundError]:
        async with self.control_plane_uow:
            match = await self.control_plane_uow.as2_partnerships.get_partnership_by_as2_ids(
                as2_from=as2_from, as2_to=as2_to
            )
            if not match:
                return Result.fail(
                    As2InboundError.partnership_not_found(
                        as2_from=as2_from, as2_to=as2_to, message_id=message_id
                    )
                )
            return Result.ok(match)

    async def _retrieve_secret_or_raise(
        self,
        vault_ref: str,
        *,
        partner_id: str,
        purpose: str,
    ) -> bytes:
        try:
            return await self.secret_store.retrieve_secret(vault_ref)
        except Exception as exc:
            logger.exception(
                "as2_secret_retrieval_failed",
                partner_id=partner_id,
                purpose=purpose,
                vault_ref=vault_ref,
            )
            raise OrchestrationError(
                f"Failed to retrieve AS2 {purpose} from secret store."
            ) from exc

    async def _retrieve_keys(
        self, local_partner: AS2Partner, remote_partner: AS2Partner
    ) -> tuple[bytes | None, bytes | None, bytes | None]:
        local_priv_key = None
        local_cert = None
        remote_cert = None

        if local_partner.private_key_vault_ref:
            local_priv_key = await self._retrieve_secret_or_raise(
                local_partner.private_key_vault_ref,
                partner_id=local_partner.id,
                purpose="local_private_key",
            )
        if local_partner.public_cert_vault_ref:
            local_cert = await self._retrieve_secret_or_raise(
                local_partner.public_cert_vault_ref,
                partner_id=local_partner.id,
                purpose="local_public_cert",
            )
        elif local_partner.public_cert_pem:
            local_cert = local_partner.public_cert_pem.encode()

        if remote_partner.public_cert_vault_ref:
            remote_cert = await self._retrieve_secret_or_raise(
                remote_partner.public_cert_vault_ref,
                partner_id=remote_partner.id,
                purpose="remote_public_cert",
            )
        elif remote_partner.public_cert_pem:
            remote_cert = remote_partner.public_cert_pem.encode()

        if not local_priv_key:
            logger.info(
                "as2_local_private_key_not_configured",
                local_partner_id=local_partner.id,
            )

        return local_priv_key, local_cert, remote_cert

    def _unbox_payload(
        self,
        as2_msg: AS2Message,
        original_headers: Mapping[str, str],
        local_priv_key: bytes | None,
        local_cert: bytes | None,
        remote_cert: bytes | None,
    ) -> Result[tuple[bytes, str | None], As2InboundError]:
        """Executes the cryptographic pipeline sequentially: Decrypt -> Re-evaluate -> Verify -> MIC."""
        current_entity = as2_msg.payload
        is_encrypted = as2_msg.is_encrypted
        is_signed = as2_msg.is_signed

        # Decryption Step
        if is_encrypted:
            if not local_priv_key:
                return Result.fail(
                    As2InboundError.decryption_failed(
                        reason="local private key is missing",
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                    )
                )
            decrypt_res = self._decrypt_entity(
                current_entity, original_headers, local_priv_key, local_cert, as2_msg
            )
            if decrypt_res.is_err:
                return Result.fail(decrypt_res.unwrap_err())
            current_entity = decrypt_res.unwrap()

            if not is_signed:
                parsed_inner = email.message_from_bytes(current_entity, policy=policy.HTTP)
                inner_ct = parsed_inner.get_content_type()
                if inner_ct in ("multipart/signed", "application/pkcs7-signature"):
                    is_signed = True

        # Verification Step
        mic: str | None = None
        if is_signed:
            if not remote_cert:
                return Result.fail(
                    As2InboundError.authentication_failed(
                        reason="remote public certificate is missing",
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                    )
                )
            if not is_encrypted:
                verify_entity = self._reconstruct_smime_headers(original_headers) + current_entity
            else:
                verify_entity = current_entity

            verify_res = self._verify_and_calculate_mic(verify_entity, remote_cert, as2_msg)
            if verify_res.is_err:
                return Result.fail(verify_res.unwrap_err())
            mic, raw_signed_content = verify_res.unwrap()
            current_entity = raw_signed_content
        else:
            mic = calculate_mic(current_entity, "sha256")
            logger.info(
                "as2_mic_calculated_unsigned",
                message_id=as2_msg.message_id,
                mic=mic,
            )

        return Result.ok((current_entity, mic))

    def _decrypt_entity(
        self,
        current_entity: bytes,
        original_headers: Mapping[str, str],
        priv_key: bytes,
        cert: bytes | None,
        as2_msg: AS2Message,
    ) -> Result[bytes, As2InboundError]:
        try:
            decrypted = self.crypto_service.decrypt(
                current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert or b"",
            )
            if decrypted:
                return Result.ok(decrypted)
        except (ValueError, TypeError, KeyError) as exc:
            logger.debug("as2_decrypt_initial_attempt_failed_trying_fallback", error=str(exc))

        # External Interoperability Fallback: prepend reconstructed S/MIME headers before retrying.
        smime_headers = self._reconstruct_smime_headers(original_headers)
        try:
            decrypted = self.crypto_service.decrypt(
                smime_headers + current_entity,
                private_key_pem=priv_key,
                public_cert_pem=cert or b"",
            )
            if decrypted:
                return Result.ok(decrypted)
            return Result.fail(
                As2InboundError.decryption_failed(
                    reason="decryption returned empty result",
                    as2_from=as2_msg.as2_from,
                    as2_to=as2_msg.as2_to,
                    message_id=as2_msg.message_id,
                )
            )
        except Exception as exc:
            logger.exception(
                "as2_decryption_failed_after_fallback",
                as2_from=as2_msg.as2_from,
                as2_to=as2_msg.as2_to,
                message_id=as2_msg.message_id,
            )
            return Result.fail(
                As2InboundError.decryption_failed(
                    reason=str(exc),
                    as2_from=as2_msg.as2_from,
                    as2_to=as2_msg.as2_to,
                    message_id=as2_msg.message_id,
                )
            )

    def _reconstruct_smime_headers(self, headers: Mapping[str, str]) -> bytes:
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
        self, verify_entity: bytes, remote_cert: bytes, as2_msg: AS2Message
    ) -> Result[tuple[str, bytes], As2InboundError]:
        msg = email.message_from_bytes(verify_entity, policy=policy.HTTP)
        boundary = msg.get_boundary()

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
            message_id=as2_msg.message_id,
            mic=mic,
        )

        try:
            is_valid, verified_payload = self.crypto_service.verify_signature(
                verify_entity, public_cert_pem=remote_cert
            )
            if not is_valid:
                return Result.fail(
                    As2InboundError.authentication_failed(
                        reason="signature verification mathematically failed",
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                    )
                )
            return Result.ok((mic, verified_payload))
        except Exception as exc:
            logger.exception(
                "as2_signature_verification_failed",
                as2_from=as2_msg.as2_from,
                as2_to=as2_msg.as2_to,
                message_id=as2_msg.message_id,
            )
            return Result.fail(
                As2InboundError.authentication_failed(
                    reason=str(exc),
                    as2_from=as2_msg.as2_from,
                    as2_to=as2_msg.as2_to,
                    message_id=as2_msg.message_id,
                )
            )

    def _extract_pure_edi(self, final_payload_bytes: bytes) -> bytes:
        parsed_msg = email.message_from_bytes(final_payload_bytes, policy=policy.HTTP)
        if "content-type" in parsed_msg:
            decoded_payload = parsed_msg.get_payload(decode=True)
            if decoded_payload is not None and isinstance(decoded_payload, bytes):
                return decoded_payload
            return parsed_msg.as_bytes()
        return final_payload_bytes

    def _extract_isa_headers(
        self,
        pure_edi_bytes: bytes,
        *,
        as2_from: str,
        as2_to: str,
        message_id: str,
    ) -> Result[_ExtractedIsaMetadata, As2InboundError]:
        """Lightweight ISA parser extracting Sender, Receiver, ST Transaction Type, and ISA13 Control No."""
        content = pure_edi_bytes.decode("ascii", errors="ignore")
        if not content.startswith("ISA"):
            return Result.fail(
                As2InboundError.invalid_payload(
                    reason="Payload does not begin with ISA segment",
                    as2_from=as2_from,
                    as2_to=as2_to,
                    message_id=message_id,
                )
            )

        element_separator = content[3]
        isa_segment = content[:106]
        elements = isa_segment.split(element_separator)

        if len(elements) < 9:
            return Result.fail(
                As2InboundError.invalid_payload(
                    reason="Malformed ISA segment",
                    as2_from=as2_from,
                    as2_to=as2_to,
                    message_id=message_id,
                )
            )

        isa_sender = elements[6].strip()
        isa_receiver = elements[8].strip()
        interchange_control_no = (
            elements[13].strip() if len(elements) > 13 and elements[13].strip() else None
        )

        st_match = re.search(rf"ST\{element_separator}(.*?)\{element_separator}", content)
        transaction_type = st_match.group(1).strip() if st_match else None

        return Result.ok(
            _ExtractedIsaMetadata(
                isa_sender=isa_sender,
                isa_receiver=isa_receiver,
                transaction_type=transaction_type,
                interchange_control_no=interchange_control_no,
            )
        )

    async def _resolve_tenant_for_isa(
        self,
        *,
        isa_sender: str,
        isa_receiver: str,
        transaction_type: str | None,
        as2_msg: AS2Message,
    ) -> Result[tuple[str, IsaTenantResolution], As2InboundError]:
        async with self.control_plane_uow:
            resolution = await self.control_plane_uow.inbound_routes.resolve_tenant_by_isa(
                isa_sender,
                isa_receiver,
                transaction_type=transaction_type,
            )

        match resolution.status:
            case IsaResolutionStatus.ACTIVE if resolution.tenant_id:
                return Result.ok((resolution.tenant_id, resolution))
            case IsaResolutionStatus.INACTIVE if resolution.tenant_id:
                return Result.ok((resolution.tenant_id, resolution))
            case IsaResolutionStatus.AMBIGUOUS:
                return Result.fail(
                    As2InboundError.ambiguous_isa_route(
                        isa_sender=isa_sender,
                        isa_receiver=isa_receiver,
                        matched_tenant_ids=resolution.matched_tenant_ids,
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                    )
                )
            case IsaResolutionStatus.PLATFORM_ONLY:
                return Result.fail(
                    As2InboundError.tenant_not_found(
                        isa_sender=isa_sender,
                        isa_receiver=isa_receiver,
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                        reason="route_owned_by_platform_sentinel",
                    )
                )
            case _:
                return Result.fail(
                    As2InboundError.tenant_not_found(
                        isa_sender=isa_sender,
                        isa_receiver=isa_receiver,
                        as2_from=as2_msg.as2_from,
                        as2_to=as2_msg.as2_to,
                        message_id=as2_msg.message_id,
                    )
                )

    async def _save_inbound_message(
        self,
        *,
        true_tenant_id: str,
        isa_meta: _ExtractedIsaMetadata,
        partnership: AS2Partnership,
        remote_partner: AS2Partner,
        as2_msg: AS2Message,
        pure_edi_bytes: bytes,
        routing_error: EdiError | None = None,
        mdn_response: str | None = None,
    ) -> str:
        logger.info(
            "as2_transaction_saving",
            isa_sender=isa_meta.isa_sender,
            isa_receiver=isa_meta.isa_receiver,
            transaction_type=isa_meta.transaction_type,
            true_tenant_id=true_tenant_id,
            routing_error_code=routing_error.code.value if routing_error else None,
            message_id=as2_msg.message_id,
        )

        format_standard: str | None = None
        if pure_edi_bytes.startswith(b"ISA"):
            format_standard = EdiStandard.X12.value.upper()
        elif pure_edi_bytes.startswith((b"UNA", b"UNB")):
            format_standard = EdiStandard.EDIFACT.value.upper()

        file_name = None
        content_disposition = as2_msg.headers.get("content-disposition")
        if content_disposition:
            match = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
            file_name = match.group(1) if match else content_disposition

        content_type = as2_msg.headers.get("content-type")
        msg_headers_json = json.dumps(as2_msg.headers)

        trace_id = generate_id(SystemIdPrefix.TRACE)
        async with self.dp_factory.get_data_plane_uow(true_tenant_id, "edi") as dp_uow:
            edi_message_id = generate_id(DomainIdPrefix.EDI_MESSAGE)
            edi_message_aggregate = EdiMessage(
                id=edi_message_id,
                tenant_id=true_tenant_id,
                trace_id=trace_id,
                original_trace_id=trace_id,
                direction=Direction(EdiDirection.INBOUND.value),
                connection_type=EdiConnectionType.AS2.value,
                sender_id=isa_meta.isa_sender,
                receiver_id=isa_meta.isa_receiver,
                transaction_type=isa_meta.transaction_type,
                interchange_control_no=isa_meta.interchange_control_no,
                file_size_bytes=len(pure_edi_bytes),
                as2_sender_id=as2_msg.as2_from,
                as2_receiver_id=as2_msg.as2_to,
                message_id=as2_msg.message_id,
                mdn_mode=partnership.mdn_type,
                mdn_response=mdn_response,
                file_name=file_name,
                content_type=content_type,
                signature_algorithm=partnership.signature_algorithm,
                encryption_algorithm=partnership.encryption_algorithm,
                status_message=None,
                state=_INITIAL_MESSAGE_STATE,
                msg_headers=msg_headers_json,
                format_standard=format_standard,
                trading_partner_id=remote_partner.id,
                edi_data=pure_edi_bytes.decode("utf-8", errors="ignore"),
                status=RecordStatus(MessageStatus.RECEIVED.value),
            )

            if routing_error is None:
                edi_message_aggregate.record_received(
                    as2_sender=as2_msg.as2_from,
                    as2_receiver=as2_msg.as2_to,
                )
                edi_message_aggregate.request_transformation(
                    edi_message_id=edi_message_id,
                    sender_id=isa_meta.isa_sender,
                    receiver_id=isa_meta.isa_receiver,
                    idempotency_key=edi_message_id,
                )
            else:
                edi_message_aggregate.attach_error(routing_error)
                edi_message_aggregate.record_received(
                    as2_sender=as2_msg.as2_from,
                    as2_receiver=as2_msg.as2_to,
                    error_code=routing_error.code.value,
                    reason=routing_error.message,
                )

            await dp_uow.edi_messages.save(edi_message_aggregate)
            await dp_uow.commit()

            return edi_message_id
