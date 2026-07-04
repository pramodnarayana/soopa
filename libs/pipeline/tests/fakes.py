from typing import Any

from pipeline.ports.repository import RepositoryPort
from pipeline.ports.storage import StoragePort
from pipeline.ports.transformer import TransformerPort


class InMemoryStorageAdapter(StoragePort):
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.upload_count = 0

    async def download(self, uri: str) -> bytes:
        if uri not in self.store:
            raise FileNotFoundError(f"URI not found in fake storage: {uri}")
        return self.store[uri]

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        normalized_prefix = key_prefix.strip("/")
        uri = f"s3://fake-bucket/{normalized_prefix}/{file_name}"
        self.store[uri] = payload
        self.upload_count += 1
        return uri


class FakeTransformerAdapter(TransformerPort):
    def __init__(self) -> None:
        self.translate_edi_calls: list[dict[str, Any]] = []
        self.translate_json_calls: list[dict[str, Any]] = []

    async def translate_edi_to_json(
        self, payload: bytes, standard: str, transaction_type: str
    ) -> dict[str, Any]:
        self.translate_edi_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        return {"fake": "json", "from": standard, "type": transaction_type}

    async def translate_json_to_edi(
        self, payload: dict[str, Any], standard: str, transaction_type: str
    ) -> bytes:
        self.translate_json_calls.append(
            {"payload": payload, "standard": standard, "transaction_type": transaction_type}
        )
        return b"FAKE*EDI*DATA~"


class InMemoryRepositoryAdapter(RepositoryPort):
    def __init__(self) -> None:
        self.edi_messages: dict[str, dict[str, Any]] = {}
        self.api_gateway: dict[str, dict[str, Any]] = {}
        self.outbox: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []
        self.webhooks: dict[str, dict[str, Any]] = {}
        self.sftp_partners: dict[str, dict[str, Any]] = {}
        self.as2_partners: dict[str, dict[str, Any]] = {}
        self.local_as2_partners: dict[str, dict[str, Any]] = {}

    async def get_edi_message(self, trace_id: str) -> dict[str, Any] | None:
        return self.edi_messages.get(trace_id)

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["status"] = status

    async def claim_edi_message(self, trace_id: str) -> bool:
        msg = self.edi_messages.get(trace_id)
        if msg and msg["status"] == "PENDING_DELIVERY":
            msg["status"] = "PROCESSING"
            return True
        return False

    async def save_api_payload(
        self, trace_id: str, direction: str, s3_uri: str, status: str
    ) -> None:
        self.api_gateway[trace_id] = {
            "trace_id": trace_id,
            "direction": direction,
            "request": s3_uri,
            "status": status,
        }

    async def publish_outbox_event(
        self, idempotency_key: str, event_type: str, payload: dict[str, Any]
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

    async def get_api_payload(self, trace_id: str) -> dict[str, Any] | None:
        return self.api_gateway.get(trace_id)

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.api_gateway:
            self.api_gateway[trace_id]["status"] = status

    async def claim_api_payload(self, trace_id: str) -> bool:
        payload = self.api_gateway.get(trace_id)
        if payload and payload["status"] == "PENDING_DELIVERY":
            payload["status"] = "PROCESSING"
            return True
        return False

    async def get_route(
        self, direction: str, sender_id: str, receiver_id: str, transaction_type: str
    ) -> dict[str, Any] | None:
        candidates = [
            r
            for r in self.routes
            if r.get("direction") == direction
            and r.get("isa_sender_id") == sender_id
            and r.get("isa_receiver_id") == receiver_id
            and r.get("transaction_type") in (transaction_type, "*")
        ]

        # Prefer exact match over wildcard
        exact_match = next(
            (r for r in candidates if r.get("transaction_type") == transaction_type), None
        )
        if exact_match:
            return exact_match

        wildcard_match = next((r for r in candidates if r.get("transaction_type") == "*"), None)
        return wildcard_match

    async def get_sftp_partner(self, partner_id: str) -> dict[str, Any] | None:
        return self.sftp_partners.get(partner_id)

    async def get_webhook(self, partner_id: str) -> dict[str, Any] | None:
        return self.webhooks.get(partner_id)

    async def get_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        return self.as2_partners.get(partner_id)

    async def get_local_as2_partner(self, partner_id: str) -> dict[str, Any] | None:
        return self.local_as2_partners.get(partner_id)


# ---------------------------------------------------------------------------
# Delivery Port Fakes — single source of truth for all test files (DRY)
# ---------------------------------------------------------------------------


class FakeHttpDeliveryAdapter:
    """Records all webhook delivery calls. Configurable response status code."""

    def __init__(self, status_code: int = 200) -> None:
        self.delivered: list[dict[str, Any]] = []
        self.status_code = status_code

    async def deliver(self, url: str, payload: bytes, auth_token: str | None = None) -> int:
        self.delivered.append({"url": url, "payload": payload, "auth_token": auth_token})
        return self.status_code


class FakeSftpDeliveryAdapter:
    """Records all SFTP delivery calls. Always succeeds."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, Any]] = []

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
        self.delivered: list[dict[str, Any]] = []
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
            raise Exception("Mock delivery failure")

        import base64
        import hashlib

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
