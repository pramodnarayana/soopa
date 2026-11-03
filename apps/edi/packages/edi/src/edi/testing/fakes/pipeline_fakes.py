import base64
import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from database.outbox_serializer import serialize_domain_event
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id
from strace.testing import InMemoryTraceRepository

from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.domain.routing.enums import EdiConnectionType, EdiDirection, ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.domain.routing.outbound_route import OutboundRoute
from edi.domain.routing.webhook import Webhook
from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.gateway_receipt import ApiGatewayReceipt
from edi.domain.transaction.stage_filter import StageFilterCriterion
from edi.ports.outbound.api_gateway_repository import ApiGatewayRepositoryPort
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.transformer_port import ParsedEdiMessage, TransformerPort

if TYPE_CHECKING:
    from edi.domain.routing.outbound_header import EdiEnvelopeHeaders


def _opt_str(val: object) -> str | None:
    if val is None:
        return None
    return str(val)


def _opt_datetime(val: object) -> datetime | None:
    if isinstance(val, datetime):
        return val
    return None


def _req_datetime(val: object, fallback: datetime) -> datetime:
    if isinstance(val, datetime):
        return val
    return fallback


def _coerce_direction(val: object, default: EdiDirection = EdiDirection.INBOUND) -> EdiDirection:
    if isinstance(val, EdiDirection):
        return val
    if isinstance(val, str) and val:
        return EdiDirection(val)
    return default


def _coerce_status(val: object, default: MessageStatus = MessageStatus.RECEIVED) -> MessageStatus:
    if isinstance(val, MessageStatus):
        return val
    if isinstance(val, str) and val:
        return MessageStatus(val)
    return default


def _edi_json_from_dict(data: dict[str, object] | None) -> EdiJson | None:
    if not data:
        return None
    now = datetime.now(UTC)
    raw_replay = data.get("replay_count", 0)
    raw_meta = data.get("business_metadata")
    raw_err_details = data.get("error_details")
    return EdiJson(
        id=str(data.get("id") or generate_id(SystemIdPrefix.GENERIC)),
        trace_id=str(data.get("trace_id") or ""),
        tenant_id=str(data["tenant_id"]) if data.get("tenant_id") is not None else "",
        direction=_coerce_direction(data.get("direction"), EdiDirection.INBOUND),
        status=_coerce_status(data.get("status"), MessageStatus.PENDING),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        status_message=_opt_str(data.get("status_message")),
        error_code=_opt_str(data.get("error_code")),
        error_details=cast(JsonDict, dict(raw_err_details))
        if isinstance(raw_err_details, dict)
        else None,
        replay_count=raw_replay if isinstance(raw_replay, int) else 0,
        parent_trace_id=_opt_str(data.get("parent_trace_id")),
        original_trace_id=_opt_str(data.get("original_trace_id")),
        trading_partner_id=_opt_str(data.get("trading_partner_id")),
        transaction_type=_opt_str(data.get("transaction_type")),
        standard=_opt_str(data.get("standard")),
        business_metadata=cast(dict[str, JsonValue], dict(raw_meta))
        if isinstance(raw_meta, dict)
        else None,
        payload=cast(JsonValue, data.get("payload")),
        storage_uri=_opt_str(data.get("storage_uri")),
    )


def _edi_message_from_dict(data: dict[str, object] | None) -> EdiMessage | None:
    if not data:
        return None
    now = datetime.now(UTC)
    raw_replay = data.get("replay_count", 0)
    raw_size = data.get("file_size_bytes")
    raw_headers = data.get("headers")
    raw_err_details = data.get("error_details")
    return EdiMessage(
        id=str(data.get("id") or generate_id(SystemIdPrefix.GENERIC)),
        trace_id=str(data.get("trace_id") or ""),
        tenant_id=str(data["tenant_id"]) if data.get("tenant_id") is not None else "",
        direction=_coerce_direction(data.get("direction"), EdiDirection.INBOUND),
        status=_coerce_status(data.get("status"), MessageStatus.RECEIVED),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        status_message=_opt_str(data.get("status_message")),
        error_code=_opt_str(data.get("error_code")),
        error_details=cast(JsonDict, dict(raw_err_details))
        if isinstance(raw_err_details, dict)
        else None,
        replay_count=raw_replay if isinstance(raw_replay, int) else 0,
        parent_trace_id=_opt_str(data.get("parent_trace_id")),
        original_trace_id=_opt_str(data.get("original_trace_id")),
        format_standard=_opt_str(data.get("format_standard")),
        transaction_type=_opt_str(data.get("transaction_type")),
        connection_type=_opt_str(data.get("connection_type")),
        sender_id=_opt_str(data.get("sender_id")),
        receiver_id=_opt_str(data.get("receiver_id")),
        gs_sender_id=_opt_str(data.get("gs_sender_id")),
        gs_receiver_id=_opt_str(data.get("gs_receiver_id")),
        trading_partner_id=_opt_str(data.get("trading_partner_id")),
        as2_sender_id=_opt_str(data.get("as2_sender_id")),
        as2_receiver_id=_opt_str(data.get("as2_receiver_id")),
        message_id=_opt_str(data.get("message_id")),
        mdn_id=_opt_str(data.get("mdn_id")),
        mdn_mode=_opt_str(data.get("mdn_mode")),
        mdn_response=_opt_str(data.get("mdn_response")),
        file_name=_opt_str(data.get("file_name")),
        content_type=_opt_str(data.get("content_type")),
        signature_algorithm=_opt_str(data.get("signature_algorithm")),
        encryption_algorithm=_opt_str(data.get("encryption_algorithm")),
        state=_opt_str(data.get("state")),
        msg_headers=_opt_str(data.get("msg_headers")),
        edi_data=_opt_str(data.get("edi_data")),
        response=_opt_str(data.get("response")),
        headers=cast(dict[str, JsonValue], dict(raw_headers))
        if isinstance(raw_headers, dict)
        else None,
        storage_uri=_opt_str(data.get("storage_uri")),
        interchange_control_no=_opt_str(data.get("interchange_control_no")),
        file_size_bytes=raw_size if isinstance(raw_size, int) else None,
    )


def _outbound_edi_header_from_dict(
    data: dict[str, object] | None,
) -> OutboundEdiHeader | None:
    if not data:
        return None
    now = datetime.now(UTC)
    return OutboundEdiHeader(
        id=str(data.get("id") or "hdr-fake"),
        tenant_id=str(data.get("tenant_id") or ""),
        trading_partner_id=str(data.get("trading_partner_id") or ""),
        isa_sender_id=str(data.get("isa_sender_id") or ""),
        isa_receiver_id=str(data.get("isa_receiver_id") or ""),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        name=_opt_str(data.get("name")),
        isa_sender_qualifier=_opt_str(data.get("isa_sender_qualifier")),
        isa_receiver_qualifier=_opt_str(data.get("isa_receiver_qualifier")),
        gs_sender_id=_opt_str(data.get("gs_sender_id")),
        gs_receiver_id=_opt_str(data.get("gs_receiver_id")),
        transaction_type=_opt_str(data.get("transaction_type")),
        default_standard=_opt_str(data.get("default_standard")),
        default_version=_opt_str(data.get("default_version")),
        isa_control_version=_opt_str(data.get("isa_control_version")),
        isa_usage_indicator=_opt_str(data.get("isa_usage_indicator")),
        gs_version=_opt_str(data.get("gs_version")),
        segment_terminator=_opt_str(data.get("segment_terminator")),
        element_separator=_opt_str(data.get("element_separator")),
        subelement_separator=_opt_str(data.get("subelement_separator")),
    )


def _sftp_partner_from_dict(data: dict[str, object] | None) -> SFTPPartner | None:
    if not data:
        return None
    now = datetime.now(UTC)
    raw_port = data.get("port", 22)
    port = int(raw_port) if isinstance(raw_port, (int, str)) else 22
    raw_pwd = (
        data.get("password_encrypted") if "password_encrypted" in data else data.get("password")
    )
    return SFTPPartner(
        id=str(data.get("id") or "sftp-fake"),
        tenant_id=str(data.get("tenant_id") or ""),
        name=str(data.get("name") or ""),
        host=str(data.get("host") or ""),
        port=port,
        username=str(data.get("username") or ""),
        active=bool(data.get("active", True)),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        host_key=_opt_str(data.get("host_key")),
        inbound_remote_path=_opt_str(data.get("inbound_remote_path")),
        outbound_remote_path=_opt_str(data.get("outbound_remote_path")),
        password_encrypted=_opt_str(raw_pwd),
        credentials_vault_ref=_opt_str(data.get("credentials_vault_ref")),
        deleted_at=_opt_datetime(data.get("deleted_at")),
    )


def _webhook_from_dict(data: dict[str, object] | None) -> Webhook | None:
    if not data:
        return None
    now = datetime.now(UTC)
    return Webhook(
        id=str(data.get("id") or "wh-fake"),
        tenant_id=str(data.get("tenant_id") or ""),
        name=str(data.get("name") or ""),
        url=str(data.get("url") or ""),
        active=bool(data.get("active", True)),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        auth_header_vault_ref=_opt_str(data.get("auth_header_vault_ref")),
    )


def _as2_partner_from_dict(data: dict[str, object] | None) -> AS2Partner | None:
    if not data:
        return None
    now = datetime.now(UTC)
    return AS2Partner(
        id=str(data.get("id") or "as2p-fake"),
        as2_id=str(data.get("as2_id") or ""),
        name=str(data.get("name") or ""),
        is_local=bool(data.get("is_local", False)),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        tenant_id=_opt_str(data.get("tenant_id")),
        public_cert_pem=_opt_str(data.get("public_cert_pem")),
        public_cert_vault_ref=_opt_str(data.get("public_cert_vault_ref")),
        private_key_vault_ref=_opt_str(data.get("private_key_vault_ref")),
        prev_public_cert_pem=_opt_str(data.get("prev_public_cert_pem")),
        prev_public_cert_vault_ref=_opt_str(data.get("prev_public_cert_vault_ref")),
        prev_private_key_vault_ref=_opt_str(data.get("prev_private_key_vault_ref")),
        url=_opt_str(data.get("url")),
        active=bool(data.get("active", False)),
    )


def _as2_partnership_from_dict(
    data: dict[str, object] | None,
) -> AS2Partnership | None:
    if not data:
        return None
    now = datetime.now(UTC)
    raw_flags = data.get("advanced_flags")
    return AS2Partnership(
        id=str(data.get("id") or "as2s-fake"),
        name=str(data.get("name") or ""),
        local_partner_id=str(data.get("local_partner_id") or ""),
        remote_partner_id=str(data.get("remote_partner_id") or ""),
        mdn_type=str(data.get("mdn_type") or "SYNC"),
        encryption_algorithm=str(data.get("encryption_algorithm") or "aes256_cbc"),
        signature_algorithm=str(data.get("signature_algorithm") or "sha256"),
        created_at=_req_datetime(data.get("created_at"), now),
        updated_at=_req_datetime(data.get("updated_at"), now),
        tenant_id=_opt_str(data.get("tenant_id")),
        credentials_vault_ref=_opt_str(data.get("credentials_vault_ref")),
        mdn_url=_opt_str(data.get("mdn_url")),
        advanced_flags=cast(dict[str, JsonValue], dict(raw_flags))
        if isinstance(raw_flags, dict)
        else None,
        active=bool(data.get("active", False)),
    )


def _inbound_route_from_dict(data: dict[str, object] | None) -> InboundRoute | None:
    if not data:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    raw_mode = data.get("processing_mode")
    raw_conn = data.get("connection_type")
    raw_dir = data.get("direction")
    raw_created = data.get("created_at")
    raw_updated = data.get("updated_at")
    return InboundRoute(
        id=str(data.get("id") or "route-fake"),
        tenant_id=str(data.get("tenant_id") or ""),
        name=str(data["name"]) if data.get("name") is not None else None,
        isa_sender_id=str(data.get("isa_sender_id") or ""),
        isa_receiver_id=str(data.get("isa_receiver_id") or ""),
        active=bool(data.get("active", True)),
        created_at=raw_created if isinstance(raw_created, datetime) else now,
        updated_at=raw_updated if isinstance(raw_updated, datetime) else now,
        trading_partner_id=str(data["trading_partner_id"])
        if data.get("trading_partner_id") is not None
        else None,
        gs_sender_id=str(data["gs_sender_id"]) if data.get("gs_sender_id") is not None else None,
        gs_receiver_id=str(data["gs_receiver_id"])
        if data.get("gs_receiver_id") is not None
        else None,
        transaction_type=str(data["transaction_type"])
        if data.get("transaction_type") is not None
        else None,
        processing_mode=ProcessingMode(str(raw_mode)) if raw_mode else None,
        direction=EdiDirection(str(raw_dir)) if raw_dir else EdiDirection.INBOUND,
        webhook_id=str(data["webhook_id"]) if data.get("webhook_id") else None,
        as2_partner_id=str(data["as2_partner_id"]) if data.get("as2_partner_id") else None,
        sftp_partner_id=str(data["sftp_partner_id"]) if data.get("sftp_partner_id") else None,
        connection_type=EdiConnectionType(str(raw_conn)) if raw_conn else None,
        destination_name=str(data["destination_name"])
        if data.get("destination_name") is not None
        else None,
    )


def _outbound_route_from_dict(data: dict[str, object] | None) -> OutboundRoute | None:
    if not data:
        return None
    now = datetime.now(UTC).replace(tzinfo=None)
    raw_conn = data.get("connection_type")
    raw_dir = data.get("direction")
    wh_id = data.get("webhook_id") or data.get("webhook_partner_id")
    raw_created = data.get("created_at")
    raw_updated = data.get("updated_at")
    return OutboundRoute(
        id=str(data.get("id") or "route-fake"),
        tenant_id=str(data.get("tenant_id") or ""),
        trading_partner_id=str(data["trading_partner_id"])
        if data.get("trading_partner_id") is not None
        else None,
        name=str(data["name"]) if data.get("name") is not None else None,
        active=bool(data.get("active", True)),
        created_at=raw_created if isinstance(raw_created, datetime) else now,
        updated_at=raw_updated if isinstance(raw_updated, datetime) else now,
        direction=EdiDirection(str(raw_dir)) if raw_dir else EdiDirection.OUTBOUND,
        as2_partner_id=str(data["as2_partner_id"]) if data.get("as2_partner_id") else None,
        sftp_partner_id=str(data["sftp_partner_id"]) if data.get("sftp_partner_id") else None,
        webhook_id=str(wh_id) if wh_id else None,
        connection_type=EdiConnectionType(str(raw_conn)) if raw_conn else None,
        destination_name=str(data["destination_name"])
        if data.get("destination_name") is not None
        else None,
    )


class FakeOutboxPublisher:
    def __init__(self) -> None:
        self.published_events: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published_events.append(event)

    async def publish_batch(self, events: list[EventEnvelope]) -> list[str]:
        self.published_events.extend(events)
        return [str(env.id) for env in events]


class InMemoryStorageAdapter(StoragePort):
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.upload_count = 0

    async def download(self, uri: str) -> bytes:
        if uri not in self.store:
            raise RuntimeError(f"URI not found in fake storage: {uri}")
        val = self.store.get(uri)
        if val is None:
            raise FileNotFoundError()
        return val

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        normalized_prefix = key_prefix.strip("/")
        uri = f"s3://fake-bucket/{normalized_prefix}/{file_name}"
        self.store[uri] = payload
        self.upload_count += 1
        return uri


class FakeTransformerAdapter(TransformerPort):
    def __init__(self) -> None:
        self.transform_edi_calls: list[dict[str, object]] = []
        self.transform_json_calls: list[dict[str, object]] = []
        self.fake_return_transactions: list[ParsedEdiMessage] | None = None

    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[ParsedEdiMessage]:
        self.transform_edi_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        if self.fake_return_transactions is not None:
            return self.fake_return_transactions
        return [
            ParsedEdiMessage(
                transaction_type=transaction_type,
                isa_sender_id="FAKE_ISA_SENDER",
                isa_receiver_id="FAKE_ISA_RECEIVER",
                gs_sender_id="FAKE_GS_SENDER",
                gs_receiver_id="FAKE_GS_RECEIVER",
                control_number="FAKE_1234",
                payload={"fake": "json", "from": standard, "type": transaction_type},
            )
        ]

    async def transform_json_to_edi(
        self,
        payload: dict[str, JsonValue] | list[dict[str, JsonValue]],
        standard: str,
        transaction_type: str,
        edi_headers: "EdiEnvelopeHeaders",
    ) -> bytes:
        self.transform_json_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        return b"FAKE*EDI*DATA~"


class InMemoryRepositoryAdapter:
    def __init__(self) -> None:
        self.edi_messages: dict[str, dict[str, object]] = {}
        self.edi_json: dict[str, dict[str, object]] = {}
        self.outbound_routes: dict[str, dict[str, object]] = {}
        self.outbound_edi_headers: dict[str, dict[str, object]] = {}
        self.outbox: list[dict[str, object]] = []
        self.routes: list[dict[str, object]] = []
        self.webhooks: dict[str, dict[str, object]] = {}
        self.sftp_partners: dict[str, dict[str, object]] = {}
        self.as2_partners: dict[str, dict[str, object]] = {}
        self.local_as2_partners: dict[str, dict[str, object]] = {}
        self.outbox_repo: FakeDataPlaneOutboxRepository | None = (
            None  # To be set by FakeDataPlaneUnitOfWork
        )

    async def get_edi_json(self, trace_id: str, tenant_id: str | None = None) -> EdiJson | None:
        raw = self.edi_json.get(trace_id)
        if not raw:
            return None

        dto_data = dict(raw)
        if "edi_json" in dto_data:
            dto_data["payload"] = dto_data["edi_json"]
        model = _edi_json_from_dict(dto_data)
        if model is not None and tenant_id and model.tenant_id and model.tenant_id != tenant_id:
            return None
        return model

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJson]:
        raw = self.edi_json.get(trace_id)
        if not raw:
            return []

        dto_data = dict(raw)
        if "edi_json" in dto_data:
            dto_data["payload"] = dto_data["edi_json"]
        model = _edi_json_from_dict(dto_data)
        if model is None:
            return []
        if tenant_id and model.tenant_id and model.tenant_id != tenant_id:
            return []
        return [model]

    async def get_outbound_edi_header_by_trading_partner_id(
        self,
        trading_partner_id: str,
        tenant_id: str | None = None,
    ) -> OutboundEdiHeader | None:
        _ = tenant_id
        data = self.outbound_edi_headers.get(trading_partner_id)
        return _outbound_edi_header_from_dict(data)

    async def update_edi_json_routing_metadata(
        self,
        trace_id: str,
        *,
        trading_partner_id: str | None = None,
        standard: str | None = None,
    ) -> None:
        if trace_id in self.edi_json:
            target = self.edi_json[trace_id]
            if trading_partner_id is not None:
                target["trading_partner_id"] = trading_partner_id
            if standard is not None:
                target["standard"] = standard

    async def update_edi_json_status(self, trace_id: str, status: MessageStatus) -> None:
        if trace_id in self.edi_json:
            self.edi_json[trace_id]["status"] = status.value

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str,
        gs_receiver_id: str,
        transaction_type: str | None = None,
    ) -> None:
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["gs_sender_id"] = gs_sender_id
            self.edi_messages[trace_id]["gs_receiver_id"] = gs_receiver_id
            self.edi_messages[trace_id]["transaction_type"] = transaction_type

    async def flush_events(self, aggregate: EdiMessage | EdiJson) -> list[EventEnvelope]:
        envelopes = []
        for event in aggregate.domain_events:
            payload_json = serialize_domain_event(event)
            if self.outbox_repo:
                envelope = await self.outbox_repo.append_event(
                    tenant_id=aggregate.tenant_id or "",
                    event_type=event.__class__.__name__,
                    payload=payload_json,
                    idempotency_key=event.idempotency_key,
                )
                if envelope:
                    envelopes.append(envelope)
        aggregate.clear_domain_events()
        return envelopes

    async def update_outbound_delivery_metadata(self, aggregate: EdiMessage) -> None:
        trace_id = aggregate.trace_id
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["status"] = aggregate.status
            self.edi_messages[trace_id]["connection_type"] = aggregate.connection_type
            self.edi_messages[trace_id]["error_code"] = aggregate.error_code
            self.edi_messages[trace_id]["status_message"] = aggregate.status_message
            self.edi_messages[trace_id]["error_details"] = aggregate.error_details

    async def save(self, aggregate: EdiMessage) -> list[EventEnvelope]:
        trace_id = aggregate.trace_id
        if not trace_id:
            trace_id = str(uuid.uuid4())
            aggregate.trace_id = trace_id

        # Merge or create message
        if trace_id not in self.edi_messages:
            self.edi_messages[trace_id] = {}

        # Serialize fields
        msg = self.edi_messages[trace_id]
        msg["id"] = str(aggregate.id) if aggregate.id else str(uuid.uuid4())
        msg["trace_id"] = trace_id
        msg["tenant_id"] = aggregate.tenant_id
        msg["direction"] = aggregate.direction.value if aggregate.direction else None
        msg["status"] = aggregate.status.value if aggregate.status else None
        msg["format_standard"] = aggregate.format_standard
        msg["transaction_type"] = aggregate.transaction_type
        msg["connection_type"] = aggregate.connection_type
        msg["sender_id"] = aggregate.sender_id
        msg["receiver_id"] = aggregate.receiver_id
        msg["gs_sender_id"] = aggregate.gs_sender_id
        msg["gs_receiver_id"] = aggregate.gs_receiver_id
        msg["edi_data"] = aggregate.edi_data
        msg["trading_partner_id"] = aggregate.trading_partner_id
        msg["storage_uri"] = aggregate.storage_uri

        for event in aggregate.domain_events:
            event_type = event.event_name
            payload = serialize_domain_event(event)
            if self.outbox_repo:
                await self.outbox_repo.append_event(
                    event_type=event_type,
                    payload=payload,
                    idempotency_key=event.idempotency_key,
                    tenant_id=aggregate.tenant_id,
                )
            else:
                self.outbox.append(
                    {
                        "idempotency_key": event.idempotency_key,
                        "event_type": event_type,
                        "payload": payload,
                    }
                )
        aggregate.clear_domain_events()
        return []

    async def save_json(self, aggregate: EdiJson) -> list[EventEnvelope]:
        trace_id = aggregate.trace_id
        if not trace_id:
            trace_id = str(uuid.uuid4())
            aggregate.trace_id = trace_id

        if trace_id not in self.edi_json:
            self.edi_json[trace_id] = {}

        record = self.edi_json[trace_id]
        record["id"] = str(aggregate.id) if aggregate.id else str(uuid.uuid4())
        record["trace_id"] = trace_id
        record["tenant_id"] = aggregate.tenant_id
        record["direction"] = aggregate.direction.value if aggregate.direction else None
        record["status"] = aggregate.status.value if aggregate.status else None
        record["trading_partner_id"] = aggregate.trading_partner_id
        record["transaction_type"] = aggregate.transaction_type
        record["standard"] = aggregate.standard
        record["business_metadata"] = aggregate.business_metadata
        record["payload"] = aggregate.payload

        for event in aggregate.domain_events:
            event_type = event.event_name
            payload = serialize_domain_event(event)
            if self.outbox_repo:
                await self.outbox_repo.append_event(
                    event_type=event_type,
                    payload=payload,
                    idempotency_key=event.idempotency_key,
                    tenant_id=aggregate.tenant_id,
                )
            else:
                self.outbox.append(
                    {
                        "idempotency_key": event.idempotency_key,
                        "event_type": event_type,
                        "payload": payload,
                    }
                )
        aggregate.clear_domain_events()
        return []

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessage | None:
        _ = tenant_id
        raw = self.edi_messages.get(trace_id)
        if raw:
            # Shallow-copy so mutations inside the domain model (or test assertions)
            # don't bleed back into the fake store and cause inter-test coupling.
            msg = dict(raw)

            # Auto-fill required fields if missing
            if "id" not in msg:
                msg["id"] = uuid.uuid4()
            if "tenant_id" not in msg:
                msg["tenant_id"] = "1"
            if "created_at" not in msg:
                msg["created_at"] = datetime.now(UTC)
            if "updated_at" not in msg:
                msg["updated_at"] = datetime.now(UTC)
            if "status" not in msg:
                msg["status"] = MessageStatus.RECEIVED
            if not msg.get("direction"):
                msg["direction"] = "INBOUND"

            # Convert non-UUID trace_id to a valid UUID string (deterministic hash)
            try:
                uuid.UUID(str(msg.get("trace_id", trace_id)))
                msg["trace_id"] = str(msg.get("trace_id", trace_id))
            except ValueError:
                # Safe: Test fake only generates dummy hash
                hashed = hashlib.md5(
                    str(msg.get("trace_id", trace_id)).encode(), usedforsecurity=False
                ).hexdigest()
                msg["trace_id"] = str(uuid.UUID(hashed))

            return _edi_message_from_dict(msg)
        return None

    async def update_edi_message_status(self, trace_id: str, status: MessageStatus) -> None:
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["status"] = status.value

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRoute | None:
        candidates = [
            r
            for r in self.routes
            if r.get("isa_sender_id") == isa_sender_id
            and r.get("isa_receiver_id") == isa_receiver_id
            and r.get("tenant_id") == tenant_id
            and r.get("transaction_type") in (transaction_type, "*")
            and r.get("active", True) is True
        ]
        exact_match = next(
            (r for r in candidates if r.get("transaction_type") == transaction_type), None
        )
        wildcard_match = next((r for r in candidates if r.get("transaction_type") == "*"), None)
        data = exact_match or wildcard_match
        return _inbound_route_from_dict(data)

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRoute | None:
        candidates = [
            r
            for r in self.routes
            if r.get("direction") == "OUTBOUND"
            and r.get("tenant_id") == tenant_id
            and (
                r.get("trading_partner_id") == trading_partner_id
                or r.get("sftp_partner_id") == trading_partner_id
                or r.get("as2_partner_id") == trading_partner_id
                or r.get("webhook_partner_id") == trading_partner_id
            )
        ]
        if candidates:
            return _outbound_route_from_dict(candidates[0])
        return None

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> SFTPPartner | None:
        _ = tenant_id
        data = self.sftp_partners.get(partner_id)
        return _sftp_partner_from_dict(data)

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> list[SFTPPartner]:
        _ = tenant_id
        results: list[SFTPPartner] = []
        for pid in ids:
            model = _sftp_partner_from_dict(self.sftp_partners.get(pid))
            if model is not None:
                results.append(model)
        return results

    async def get_webhook(self, tenant_id: str, partner_id: str) -> Webhook | None:
        _ = tenant_id
        data = self.webhooks.get(partner_id)
        return _webhook_from_dict(data)

    async def get_as2_partner(self, tenant_id: str, partner_id: str) -> AS2Partner | None:
        _ = tenant_id
        data = self.as2_partners.get(partner_id)
        if data:
            remote_data = data.get("remote") or data
            return _as2_partner_from_dict(remote_data) if isinstance(remote_data, dict) else None
        return None

    async def get_as2_partner_by_as2_id(self, tenant_id: str, as2_id: str) -> AS2Partner | None:
        _ = tenant_id
        for data in self.as2_partners.values():
            if not isinstance(data, dict):
                continue
            remote_data = data.get("remote") or data
            if isinstance(remote_data, dict) and remote_data.get("as2_id") == as2_id:
                return _as2_partner_from_dict(remote_data)
        return None

    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[str]) -> list[AS2Partner]:
        results: list[AS2Partner] = []
        for pid in ids:
            partner = await self.get_as2_partner(tenant_id, pid)
            if partner is not None:
                results.append(partner)
        return results

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2Partnership | None:
        _ = tenant_id
        for data in self.as2_partners.values():
            if not isinstance(data, dict):
                continue
            partnership_data = data.get("partnership")
            if isinstance(partnership_data, dict) and partnership_data.get("id") == partnership_id:
                return _as2_partnership_from_dict(partnership_data)
        return None

    async def get_as2_partnerships_by_remote_partner_id(
        self, tenant_id: str, remote_partner_id: str, active: bool | None = None
    ) -> list[AS2Partnership]:
        _ = tenant_id
        results = []
        for data in self.as2_partners.values():
            if not isinstance(data, dict):
                continue
            partnership_data = data.get("partnership")
            if (
                isinstance(partnership_data, dict)
                and partnership_data.get("remote_partner_id") == remote_partner_id
            ):
                if active is not None and partnership_data.get("active") != active:
                    continue
                model = _as2_partnership_from_dict(partnership_data)
                if model:
                    results.append(model)
        return results


# ---------------------------------------------------------------------------
# Delivery Port Fakes — single source of truth for all test files (DRY)
# ---------------------------------------------------------------------------


class FakeHttpDeliveryAdapter:
    """Records all webhook delivery calls. Configurable response status code."""

    def __init__(self, status_code: int = 200) -> None:
        self.delivered: list[dict[str, object]] = []
        self.status_code = status_code

    async def deliver(
        self,
        url: str,
        payload: bytes,
        auth_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[int, str]:
        self.delivered.append(
            {
                "url": url,
                "payload": payload,
                "auth_token": auth_token,
                "idempotency_key": idempotency_key,
            }
        )
        return self.status_code, "Fake response body"


class FakeSftpDeliveryAdapter:
    """Records all SFTP delivery calls. Always succeeds."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, object]] = []
        self.raise_on_deliver = False

    async def deliver(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
        client_key: str | None,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        self.delivered.append(
            {
                "host": host,
                "port": port,
                "username": username,
                "password": password,
                "host_key": host_key,
                "client_key": client_key,
                "outbound_remote_path": remote_path,
                "inbound_remote_path": remote_path,
                "filename": filename,
                "payload": payload,
            }
        )


class FakeAS2DeliveryAdapter:
    """Records all AS2 delivery calls. Returns a minimal sync MDN response."""

    def __init__(
        self,
        status_code: int = 200,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {
            "Content-Type": 'multipart/report; report-type=disposition-notification; boundary="----=_MDNBoundary"'
        }
        self.delivered: list[dict[str, object]] = []
        self.raise_on_deliver = False
        if body is not None:
            self.body = body
        else:
            self.body = (
                b"------=_MDNBoundary\r\n"
                b"Content-Type: text/plain; charset=us-ascii\r\n\r\n"
                b"The AS2 message has been processed.\r\n"
                b"------=_MDNBoundary\r\n"
                b"Content-Type: message/disposition-notification\r\n\r\n"
                b"Original-Message-ID: <msg-123>\r\n"
                b"Disposition: automatic-action/MDN-sent-automatically; processed\r\n"
                b"------=_MDNBoundary--\r\n"
            )

    async def deliver(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        self.delivered.append({"url": url, "body": body, "headers": headers})
        if self.raise_on_deliver:
            raise RuntimeError("Fake delivery failure")

        digest = hashlib.sha256(body).digest()
        mic = base64.b64encode(digest).decode("ascii") + ", sha256"

        resp_body = self.body
        if b"Received-content-MIC" not in resp_body:
            resp_body = resp_body.replace(
                b"Disposition: automatic-action/MDN-sent-automatically; processed\r\n",
                f"Disposition: automatic-action/MDN-sent-automatically; processed\r\nReceived-content-MIC: {mic}\r\n".encode(),
            )

        return self.status_code, self.headers, resp_body


class FakeVault:
    """Returns pre-seeded secrets by reference key. Raises KeyError on unknown refs."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.secrets: dict[str, str] = secrets or {}

    async def get_secret(self, ref: str) -> str:
        if ref not in self.secrets:
            raise KeyError(f"FakeVault: unknown secret ref '{ref}'")
        return self.secrets[ref]


class NullVault:
    """Always raises — use when tests must assert that Vault is never called."""

    async def get_secret(self, ref: str) -> str:
        raise AssertionError(f"NullVault.get_secret called unexpectedly with ref='{ref}'")


# ---------------------------------------------------------------------------
# Unit of Work Fakes — for testing Application Use Cases
# ---------------------------------------------------------------------------


class FakeDataPlaneOutboxRepository:
    """
    In-memory implementation of DataPlaneOutboxRepositoryPort.
    Provides full leasing semantics so tests can assert on outbox side-effects.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.leased: dict[str, str] = {}  # key_str -> owner_token
        self.processed: set[str] = set()
        self.failed: set[str] = set()

    async def append_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, JsonValue],
        idempotency_key: str | None = None,
    ) -> EventEnvelope:
        # Only deduplicate when idempotency_key is explicitly provided (not None)
        if idempotency_key is not None:
            for existing in self.events:
                if existing["idempotency_key"] == idempotency_key:
                    return EventEnvelope(
                        id=str(existing.get("id", generate_id(SystemIdPrefix.EVENT))),
                        source="edi",
                        event_type=event_type,
                        payload=payload,
                        idempotency_key=idempotency_key,
                        tenant_id=tenant_id,
                    )

        event_id = generate_id(SystemIdPrefix.EVENT)
        self.events.append(
            {
                "id": event_id,
                "idempotency_key": idempotency_key,
                "event_type": event_type,
                "payload": payload,
            }
        )
        return EventEnvelope(
            id=event_id,
            source="edi",
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
        )

    async def mark_completed(self, event_id: str, worker_id: str | None = None) -> None:
        self.processed.add(event_id)

    async def claim_delivery_outbox_event(self, key_str: str) -> str | None:
        if key_str in self.processed or key_str in self.leased:
            return None

        owner_token = generate_id(SystemIdPrefix.GENERIC)
        self.leased[key_str] = owner_token
        return owner_token

    async def mark_delivery_success(self, key_str: str, owner_token: str) -> None:
        if self.leased.get(key_str) == owner_token:
            del self.leased[key_str]
            self.processed.add(key_str)

    async def mark_delivery_failure(self, key_str: str, owner_token: str) -> None:
        if self.leased.get(key_str) == owner_token:
            del self.leased[key_str]
            self.failed.add(key_str)


class FakeEdiMessageRepository:
    """Single-aggregate EdiMessageRepositoryPort test double backed by InMemoryRepositoryAdapter."""

    def __init__(self, backing: InMemoryRepositoryAdapter) -> None:
        self._backing = backing

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessage | None:
        return await self._backing.get_edi_message(trace_id, tenant_id=tenant_id)

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: Sequence[str]
    ) -> Sequence[EdiMessage]:
        results: list[EdiMessage] = []
        for trace_id in trace_ids:
            msg = await self._backing.get_edi_message(trace_id, tenant_id=tenant_id)
            if msg is not None and msg.tenant_id == tenant_id:
                results.append(msg)
        return results

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessage]:
        _ = (partner_id, transaction_type, direction)
        items: list[EdiMessage] = []
        for trace_id in list(self._backing.edi_messages.keys()):
            msg = await self._backing.get_edi_message(trace_id, tenant_id=tenant_id)
            if msg is not None and msg.tenant_id == tenant_id:
                items.append(msg)
        return items[offset : offset + limit]

    async def explorer_list_edi_messages(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiMessage]:
        _ = filters
        return await self.list_edi_messages(tenant_id, limit=limit, offset=offset)

    async def save(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        return await self._backing.save(aggregate)

    async def save_all(self, aggregates: Sequence[EdiMessage]) -> Sequence[EventEnvelope]:
        envelopes: list[EventEnvelope] = []
        for agg in aggregates:
            envelopes.extend(await self._backing.save(agg))
        return envelopes

    async def flush_events(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]:
        return await self._backing.flush_events(aggregate)

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        transaction_type: str | None,
    ) -> None:
        await self._backing.update_edi_message_metadata(
            trace_id,
            gs_sender_id or "",
            gs_receiver_id or "",
            transaction_type=transaction_type,
        )

    async def update_edi_message_status(self, trace_id: str, status: MessageStatus) -> None:
        await self._backing.update_edi_message_status(trace_id, status)

    async def update_outbound_delivery_metadata(self, aggregate: EdiMessage) -> None:
        await self._backing.update_outbound_delivery_metadata(aggregate)

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None:
        _ = tenant_id
        for trace_id in trace_ids:
            if trace_id in self._backing.edi_messages:
                curr = self._backing.edi_messages[trace_id].get("replay_count", 0)
                self._backing.edi_messages[trace_id]["replay_count"] = (
                    curr if isinstance(curr, int) else 0
                ) + 1


class FakeEdiJsonRepository:
    """Single-aggregate EdiJsonRepositoryPort test double backed by InMemoryRepositoryAdapter."""

    def __init__(self, backing: InMemoryRepositoryAdapter) -> None:
        self._backing = backing

    async def get_edi_json(self, trace_id: str, tenant_id: str | None = None) -> EdiJson | None:
        return await self._backing.get_edi_json(trace_id, tenant_id=tenant_id)

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJson]:
        return await self._backing.get_edi_jsons_by_trace_id(trace_id, tenant_id=tenant_id)

    async def get_edi_json_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> EdiJson | None:
        _ = (tenant_id, idempotency_key)
        return None

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJson]:
        results: list[EdiJson] = []
        for trace_id in list(self._backing.edi_json.keys()):
            model = await self._backing.get_edi_json(trace_id, tenant_id=tenant_id)
            if (
                model is not None
                and model.tenant_id == tenant_id
                and model.business_metadata
                and model.business_metadata.get(key) == value
            ):
                results.append(model)
        return results

    async def explorer_list_edi_json(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiJson]:
        _ = filters
        results: list[EdiJson] = []
        for trace_id in list(self._backing.edi_json.keys()):
            model = await self._backing.get_edi_json(trace_id, tenant_id=tenant_id)
            if model is not None and model.tenant_id == tenant_id:
                results.append(model)
        return results[offset : offset + limit]

    async def save(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        return await self._backing.save_json(aggregate)

    async def flush_events(self, aggregate: EdiJson) -> Sequence[EventEnvelope]:
        return await self._backing.flush_events(aggregate)

    async def update_edi_json_routing_metadata(
        self,
        trace_id: str,
        *,
        trading_partner_id: str | None = None,
        standard: str | None = None,
    ) -> None:
        await self._backing.update_edi_json_routing_metadata(
            trace_id,
            trading_partner_id=trading_partner_id,
            standard=standard,
        )

    async def update_edi_json_status(self, trace_id: str, status: MessageStatus) -> None:
        await self._backing.update_edi_json_status(trace_id, status)

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None:
        _ = tenant_id
        for trace_id in trace_ids:
            if trace_id in self._backing.edi_json:
                curr = self._backing.edi_json[trace_id].get("replay_count", 0)
                self._backing.edi_json[trace_id]["replay_count"] = (
                    curr if isinstance(curr, int) else 0
                ) + 1


class FakeDataPlaneUnitOfWork:
    """
    In-memory Unit of Work satisfying the DataPlaneUnitOfWorkPort protocol.
    Wires FakeDataPlaneOutboxRepository and single-aggregate stage repositories together.
    """

    def __init__(
        self,
        repository: InMemoryRepositoryAdapter | None = None,
        outbox: FakeDataPlaneOutboxRepository | None = None,
    ) -> None:
        self.repository = repository or InMemoryRepositoryAdapter()
        self.edi_messages = FakeEdiMessageRepository(self.repository)
        self.edi_jsons = FakeEdiJsonRepository(self.repository)
        self.api_gateway_receipts = FakeApiGatewayRepository()
        self.traces = InMemoryTraceRepository()
        self.outbound_routes = self.repository
        self.inbound_routes = self.repository
        self.edi_headers = self.repository
        self.as2_partners = self.repository
        self.as2_partnerships = self.repository
        self.sftp_partners = self.repository
        self.webhooks = self.repository
        self.outbox = outbox or FakeDataPlaneOutboxRepository()
        self.repository.outbox_repo = self.outbox
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> "FakeDataPlaneUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        return True


class FakeControlPlaneUnitOfWork:
    def __init__(self, repository: InMemoryRepositoryAdapter) -> None:
        self.repository = repository
        self.inbound_routes = repository
        self.outbound_routes = repository
        self.edi_headers = repository
        self.webhooks = repository
        self.as2_partners = repository
        self.sftp_partners = repository
        self.as2_partnerships = repository

    async def __aenter__(self) -> "FakeControlPlaneUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: object | None,
    ) -> None:
        pass


class FakeApiGatewayRepository(ApiGatewayRepositoryPort):
    def __init__(self) -> None:
        self.api_gateway: dict[str, dict[str, JsonValue]] = {}

    async def save(self, receipt: ApiGatewayReceipt) -> str:
        trace_id = receipt.trace_id or str(uuid.uuid4())
        record_id = receipt.id or str(uuid.uuid4())
        self.api_gateway[trace_id] = {
            "id": record_id,
            "trace_id": trace_id,
            "tenant_id": receipt.tenant_id,
            "direction": receipt.direction.value if receipt.direction else None,
            "status": receipt.status.value if receipt.status else None,
            "transaction_type": receipt.transaction_type,
            "webhook_url": receipt.webhook_url,
            "http_status_code": receipt.http_status_code,
            "payload": receipt.payload,
            "response": receipt.response,
            "error_code": receipt.error_code,
            "error_details": receipt.error_details,
        }
        return record_id

    async def get_api_gateways_by_trace_id(
        self, tenant_id: str, trace_id: str
    ) -> list[ApiGatewayReceipt]:
        data = self.api_gateway.get(trace_id)
        if not data:
            return []
        if data.get("tenant_id") and data.get("tenant_id") != tenant_id:
            return []
        raw_dir = data.get("direction")
        raw_status = data.get("status")
        raw_http = data.get("http_status_code")
        return [
            ApiGatewayReceipt(
                id=str(data.get("id") or str(uuid.uuid4())),
                tenant_id=tenant_id,
                trace_id=trace_id,
                direction=EdiDirection(str(raw_dir)) if raw_dir else EdiDirection.INBOUND,
                status=MessageStatus(str(raw_status)) if raw_status else MessageStatus.PENDING,
                transaction_type=str(data["transaction_type"])
                if data.get("transaction_type") is not None
                else None,
                webhook_url=str(data["webhook_url"])
                if data.get("webhook_url") is not None
                else None,
                http_status_code=raw_http if isinstance(raw_http, int) else None,
                payload=data.get("payload"),
                response=str(data["response"]) if data.get("response") is not None else None,
            )
        ]

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: MessageStatus,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
        error_code: str | None = None,
        error_details: JsonDict | None = None,
        record_id: str | None = None,
    ) -> None:
        _ = (error_code, error_details, record_id)
        if trace_id in self.api_gateway:
            self.api_gateway[trace_id]["status"] = status.value
            if webhook_url is not None:
                self.api_gateway[trace_id]["webhook_url"] = webhook_url
            if http_status_code is not None:
                self.api_gateway[trace_id]["http_status_code"] = http_status_code
            if response is not None:
                self.api_gateway[trace_id]["response"] = response
