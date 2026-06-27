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
        self.api_payloads: dict[str, dict[str, Any]] = {}
        self.outbox: list[dict[str, Any]] = []

    async def get_edi_message(self, trace_id: str) -> dict[str, Any] | None:
        return self.edi_messages.get(trace_id)

    async def update_edi_message_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.edi_messages:
            self.edi_messages[trace_id]["status"] = status

    async def save_api_payload(
        self, trace_id: str, direction: str, s3_uri: str, status: str
    ) -> None:
        self.api_payloads[trace_id] = {
            "trace_id": trace_id,
            "direction": direction,
            "s3_key": s3_uri,
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
        return self.api_payloads.get(trace_id)

    async def update_api_payload_status(self, trace_id: str, status: str) -> None:
        if trace_id in self.api_payloads:
            self.api_payloads[trace_id]["status"] = status

    async def claim_api_payload(self, trace_id: str) -> bool:
        payload = self.api_payloads.get(trace_id)
        if payload and payload["status"] == "PENDING_DELIVERY":
            payload["status"] = "PROCESSING"
            return True
        return False
