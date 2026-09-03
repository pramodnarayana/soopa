import base64
import dataclasses
import hashlib
import uuid
from datetime import UTC, datetime
from typing import TypeVar

from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonValue
from seedwork.utils import generate_id

T = TypeVar("T")


def _from_dict(cls: type[T], data: dict[str, object] | None) -> T | None:
    if not data:
        return None

    kwargs = {}
    fields = getattr(cls, "__dataclass_fields__", {})
    for name in fields:
        if name in data:
            kwargs[name] = data[name]
        else:
            # Provide a safe default if the field is missing from test data
            f = fields[name]
            if f.default is not dataclasses.MISSING:
                kwargs[name] = f.default
            elif f.default_factory is not dataclasses.MISSING:
                kwargs[name] = f.default_factory()
            else:
                # Fallback to None. This handles Optionals cleanly.
                kwargs[name] = None

    return cls(**kwargs)


from edi.application.dtos.partners import (
    AS2PartnershipDTO,
    LocalAS2PartnerDTO,
    RemoteAS2PartnerDTO,
    SFTPPartnerDTO,
)
from edi.application.dtos.routes import InboundRouteDTO, OutboundEdiHeaderDTO, OutboundRouteDTO
from edi.application.dtos.webhooks import WebhookDTO
from edi.domain.enums import EdiDirection as MessageDirection
from edi.domain.enums import MessageStatus
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.ports.outbound.edi_message_port import RepositoryPort
from edi.ports.outbound.storage_port import StoragePort
from edi.ports.outbound.transformer_port import TransformedTransaction, TransformerPort


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
        self.mock_return_transactions: list[TransformedTransaction] | None = None

    async def transform_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> list[TransformedTransaction]:
        self.transform_edi_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        if self.mock_return_transactions is not None:
            return self.mock_return_transactions
        return [
            TransformedTransaction(
                transaction_type=transaction_type,
                isa_sender_id="MOCK_ISA_SENDER",
                isa_receiver_id="MOCK_ISA_RECEIVER",
                gs_sender_id="MOCK_GS_SENDER",
                gs_receiver_id="MOCK_GS_RECEIVER",
                control_number="MOCK_1234",
                payload={"fake": "json", "from": standard, "type": transaction_type},
            )
        ]

    async def transform_json_to_edi(
        self,
        payload: dict[str, JsonValue] | list[dict[str, JsonValue]],
        standard: str,
        transaction_type: str,
        route_config: dict[str, JsonValue],
    ) -> bytes:
        self.transform_json_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        return b"FAKE*EDI*DATA~"


class InMemoryRepositoryAdapter(RepositoryPort):
    def __init__(self) -> None:
        self.edi_messages: dict[str, dict[str, object]] = {}
        self.api_gateway: dict[str, dict[str, object]] = {}
        self.edi_json: dict[str, dict[str, object]] = {}
        self.outbound_routes: dict[str, dict[str, object]] = {}
        self.outbound_edi_headers: dict[str, dict[str, object]] = {}
        self.outbox: list[dict[str, object]] = []
        self.routes: list[dict[str, object]] = []
        self.webhooks: dict[str, dict[str, object]] = {}
        self.sftp_partners: dict[str, dict[str, object]] = {}
        self.as2_partners: dict[str, dict[str, object]] = {}
        self.local_as2_partners: dict[str, dict[str, object]] = {}

    async def get_edi_json(self, trace_id: str) -> EdiJsonDomainModel | None:
        raw = self.edi_json.get(trace_id)
        if not raw:
            return None

        dto_data = dict(raw)
        if "edi_json" in dto_data:
            dto_data["payload"] = dto_data["edi_json"]
        return _from_dict(EdiJsonDomainModel, dto_data)

    async def get_outbound_edi_header_by_route_or_partner(
        self,
        route_id: str | None = None,
        trading_partner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> OutboundEdiHeaderDTO | None:
        if trading_partner_id is None:
            return None
        data = self.outbound_edi_headers.get(trading_partner_id)
        return _from_dict(OutboundEdiHeaderDTO, data)

    async def update_edi_json(self, trace_id: str, **kwargs: object) -> None:
        if trace_id in self.edi_json:
            self.edi_json[trace_id].update(kwargs)

    async def update_edi_json_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.edi_json:
            self.edi_json[trace_id]["status"] = status

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

    async def save_edi_message(
        self,
        trace_id: str,
        direction: str,
        edi_data: str,
        format_standard: str,
        transaction_type: str,
        status: str,
        connection_type: str | None = None,
        sender_id: str | None = None,
        receiver_id: str | None = None,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
        trading_partner_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        kwargs = {
            "trace_id": trace_id,
            "direction": direction,
            "edi_data": edi_data,
            "format_standard": format_standard,
            "transaction_type": transaction_type,
            "status": status,
            "connection_type": connection_type,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "gs_sender_id": gs_sender_id,
            "gs_receiver_id": gs_receiver_id,
            "trading_partner_id": trading_partner_id,
            "tenant_id": tenant_id,
        }
        self.edi_messages[trace_id] = {k: v for k, v in kwargs.items()}

    async def get_edi_message(self, trace_id: str) -> EdiMessageDomainModel | None:
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
            if "direction" not in msg:
                msg["direction"] = MessageDirection.INBOUND

            # Convert non-UUID trace_id to a valid UUID string (deterministic hash)
            try:
                uuid.UUID(str(msg.get("trace_id", trace_id)))
                msg["trace_id"] = str(msg.get("trace_id", trace_id))
            except ValueError:
                # Safe: Test mock only generates dummy hash
                hashed = hashlib.md5(str(msg.get("trace_id", trace_id)).encode()).hexdigest()  # noqa: S324
                msg["trace_id"] = str(uuid.UUID(hashed))

            return _from_dict(EdiMessageDomainModel, msg)
        return None

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["status"] = status

    async def claim_edi_message(self, trace_id: str) -> bool:
        msg = self.edi_messages.get(trace_id)
        if msg and msg["status"] == MessageStatus.PENDING_DELIVERY:
            msg["status"] = MessageStatus.PROCESSING
            return True
        return False

    async def save_api_payload(
        self,
        trace_id: str,
        direction: str,
        payload: dict[str, JsonValue],
        status: str,
        transaction_type: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self.api_gateway[trace_id] = {
            "direction": direction,
            "payload": payload,
            "status": status,
            "transaction_type": transaction_type,
        }

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, JsonValue]
    ) -> None:
        # Idempotent: ignore duplicate events with the same key (mirrors production behavior)
        for existing in self.outbox:
            if existing["idempotency_key"] == idempotency_key:
                return
        self.outbox.append(
            {
                "idempotency_key": idempotency_key,
                "event_type": event_type,
                "payload": payload,
            }
        )

    async def get_api_payload(self, trace_id: str) -> dict[str, JsonValue] | None:
        raw = self.api_gateway.get(trace_id)
        return raw  # type: ignore

    async def update_api_payload_status(
        self,
        trace_id: str,
        status: str,
        webhook_url: str | None = None,
        http_status_code: int | None = None,
        response: str | None = None,
    ) -> None:
        if trace_id in self.api_gateway:
            self.api_gateway[trace_id]["status"] = status
            if webhook_url is not None:
                self.api_gateway[trace_id]["webhook_url"] = webhook_url
            if http_status_code is not None:
                self.api_gateway[trace_id]["http_status_code"] = http_status_code
            if response is not None:
                self.api_gateway[trace_id]["response"] = response

    async def claim_api_payload(self, trace_id: str) -> bool:
        payload = self.api_gateway.get(trace_id)
        if payload and payload["status"] == MessageStatus.PENDING_DELIVERY:
            payload["status"] = MessageStatus.PROCESSING
            return True
        return False

    async def get_route(
        self,
        direction: str,
        sender_id: str,
        receiver_id: str,
        transaction_type: str,
        gs_sender_id: str | None = None,
        gs_receiver_id: str | None = None,
    ) -> InboundRouteDTO | None:
        candidates = [
            r
            for r in self.routes
            if r.get("direction") == direction
            and r.get("isa_sender_id") == sender_id
            and r.get("isa_receiver_id") == receiver_id
            and r.get("transaction_type") in (transaction_type, "*")
        ]
        exact_match = next(
            (r for r in candidates if r.get("transaction_type") == transaction_type), None
        )
        wildcard_match = next((r for r in candidates if r.get("transaction_type") == "*"), None)
        data = exact_match or wildcard_match
        return _from_dict(InboundRouteDTO, data)

    async def get_outbound_route(self, route_id: str) -> OutboundRouteDTO | None:
        data = self.outbound_routes.get(route_id)
        return _from_dict(OutboundRouteDTO, data)

    async def save_edi_json(
        self,
        trace_id: str,
        direction: str,
        partnership_id: str | None,
        transaction_type: str | None,
        standard: str | None,
        sender_id: str | None,
        receiver_id: str | None,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        business_metadata: dict[str, JsonValue],
        payload: dict[str, JsonValue],
        status: str,
        tenant_id: str | None = None,
    ) -> str:
        self.edi_json[trace_id] = {
            "direction": direction,
            "edi_json": payload,
            "status": status,
            "transaction_type": transaction_type,
        }
        return trace_id

    async def get_outbound_route_by_trading_partner_id(
        self, trading_partner_id: str, tenant_id: str | None = None
    ) -> OutboundRouteDTO | None:
        candidates = [
            r
            for r in self.routes
            if r.get("direction") == "OUTBOUND"
            and (
                r.get("sftp_partner_id") == trading_partner_id
                or r.get("as2_partner_id") == trading_partner_id
                or r.get("webhook_partner_id") == trading_partner_id
            )
        ]
        if candidates:
            return _from_dict(OutboundRouteDTO, candidates[0])
        return None

    async def get_sftp_partner(self, partner_id: str) -> SFTPPartnerDTO | None:
        data = self.sftp_partners.get(partner_id)
        return _from_dict(SFTPPartnerDTO, data)

    async def get_webhook(self, partner_id: str) -> WebhookDTO | None:
        data = self.webhooks.get(partner_id)
        return _from_dict(WebhookDTO, data)

    async def get_as2_partner(
        self, partner_id: str
    ) -> tuple[RemoteAS2PartnerDTO, AS2PartnershipDTO] | None:
        data = self.as2_partners.get(partner_id)
        if data:
            remote_data = data.get("remote") or data
            partnership_data = data.get("partnership") or data
            remote_dto = (
                _from_dict(RemoteAS2PartnerDTO, remote_data)
                if isinstance(remote_data, dict)
                else None
            )
            partnership_dto = (
                _from_dict(AS2PartnershipDTO, partnership_data)
                if isinstance(partnership_data, dict)
                else None
            )
            if remote_dto and partnership_dto:
                return remote_dto, partnership_dto
        return None

    async def get_local_as2_partner(self, partner_id: str) -> LocalAS2PartnerDTO | None:
        data = self.local_as2_partners.get(partner_id)
        return _from_dict(LocalAS2PartnerDTO, data)


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
        return self.status_code, "Mock response body"


class FakeSftpDeliveryAdapter:
    """Records all SFTP delivery calls. Always succeeds."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, object]] = []

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
        if getattr(self, "raise_on_deliver", False):
            raise RuntimeError("Mock delivery failure")

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
        self, event_type: str, payload: dict[str, JsonValue], idempotency_key: str | None = None
    ) -> None:
        # Only deduplicate when idempotency_key is explicitly provided (not None)
        if idempotency_key is not None:
            for existing in self.events:
                if existing["idempotency_key"] == idempotency_key:
                    return
        self.events.append(
            {"idempotency_key": idempotency_key, "event_type": event_type, "payload": payload}
        )

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


class FakeDataPlaneUnitOfWork:
    """
    In-memory Unit of Work satisfying the DataPlaneUnitOfWorkPort protocol.
    Wires FakeDataPlaneOutboxRepository and InMemoryRepositoryAdapter together.
    """

    def __init__(
        self,
        repository: InMemoryRepositoryAdapter | None = None,
        outbox: FakeDataPlaneOutboxRepository | None = None,
    ) -> None:
        self.repository = repository or InMemoryRepositoryAdapter()
        self.outbox = outbox or FakeDataPlaneOutboxRepository()
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
