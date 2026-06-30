import pytest
from fakes import InMemoryRepositoryAdapter, InMemoryStorageAdapter
from pipeline.core.deliver import DeliveryService

pytestmark = pytest.mark.asyncio


class FakeHttpDeliveryAdapter:
    def __init__(self, status_code: int = 200) -> None:
        self.delivered: list[dict] = []
        self.status_code = status_code

    async def deliver(self, url: str, payload: bytes, auth_token: str | None = None) -> int:
        self.delivered.append({"url": url, "payload": payload, "auth_token": auth_token})
        return self.status_code


class FakeSftpDeliveryAdapter:
    def __init__(self) -> None:
        self.delivered: list[dict] = []

    async def deliver(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
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
                "remote_path": remote_path,
                "filename": filename,
                "payload": payload,
                "host_key": host_key,
            }
        )


async def test_delivery_service_inbound_webhook() -> None:
    # Arrange
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter()
    sftp_adapter = FakeSftpDeliveryAdapter()

    trace_id = "trace-456"
    s3_uri = "s3://fake-bucket/api_payloads/trace-456/translated.json"
    edi_s3_uri = "s3://fake-bucket/edi_messages/trace-456/raw.edi"

    storage.store[s3_uri] = b'{"hello": "world"}'

    # Needs EdiMessage to get sender/receiver/direction
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "INBOUND",
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "s3_key": edi_s3_uri,
        "status": "TRANSLATED",
    }

    repo.api_payloads[trace_id] = {
        "trace_id": trace_id,
        "s3_key": s3_uri,
        "status": "PENDING_DELIVERY",
    }

    repo.routes.append(
        {
            "route_id": "r1",
            "direction": "INBOUND",
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_partner_id": "wp1",
        }
    )
    repo.webhook_partners["wp1"] = {
        "name": "Test Webhook",
        "url": "https://webhook.example.com/edi",
        "auth_header_vault_ref": None,
    }

    # Act
    service = DeliveryService(storage, repo, http_adapter, sftp_adapter)
    await service.deliver(trace_id)

    # Assert
    assert len(http_adapter.delivered) == 1
    assert http_adapter.delivered[0]["url"] == "https://webhook.example.com/edi"
    assert repo.api_payloads[trace_id]["status"] == "DELIVERED"


async def test_delivery_service_outbound_sftp() -> None:
    # Arrange
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter()
    sftp_adapter = FakeSftpDeliveryAdapter()

    trace_id = "trace-sftp"
    edi_s3_uri = "s3://fake-bucket/edi_messages/trace-sftp/translated.edi"

    storage.store[edi_s3_uri] = b"FAKE*EDI*DATA~"

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "OUTBOUND",
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "855",
        "s3_key": edi_s3_uri,
        "status": "PENDING_DELIVERY",
    }

    repo.routes.append(
        {
            "route_id": "r2",
            "direction": "OUTBOUND",
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "*",
            "sftp_partner_id": "sftp1",
        }
    )
    repo.sftp_partners["sftp1"] = {
        "host": "sftp.example.com",
        "port": 22,
        "username": "user",
        "credentials_vault_ref": "mock_password",
        "remote_path": "/out",
    }

    # Act
    service = DeliveryService(storage, repo, http_adapter, sftp_adapter)
    await service.deliver(trace_id)

    # Assert
    assert len(sftp_adapter.delivered) == 1
    assert sftp_adapter.delivered[0]["host"] == "sftp.example.com"
    assert sftp_adapter.delivered[0]["payload"] == b"FAKE*EDI*DATA~"
    assert repo.edi_messages[trace_id]["status"] == "DELIVERED"


async def test_delivery_service_no_route_raises() -> None:
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()

    trace_id = "trace-err"
    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "INBOUND",
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
    }

    service = DeliveryService(storage, repo, FakeHttpDeliveryAdapter(), FakeSftpDeliveryAdapter())
    with pytest.raises(ValueError, match="No route found"):
        await service.deliver(trace_id)


async def test_delivery_service_http_failure_sets_failed_status() -> None:
    storage = InMemoryStorageAdapter()
    repo = InMemoryRepositoryAdapter()
    http_adapter = FakeHttpDeliveryAdapter(status_code=503)

    trace_id = "trace-fail"
    s3_uri = "s3://fake-bucket/api_payloads/trace-fail/translated.json"
    storage.store[s3_uri] = b'{"hello": "world"}'

    repo.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "direction": "INBOUND",
        "sender_id": "SENDER1",
        "receiver_id": "RECV1",
        "transaction_type": "850",
        "status": "TRANSLATED",
    }
    repo.api_payloads[trace_id] = {
        "trace_id": trace_id,
        "s3_key": s3_uri,
        "status": "PENDING_DELIVERY",
    }
    repo.routes.append(
        {
            "route_id": "r1",
            "direction": "INBOUND",
            "isa_sender_id": "SENDER1",
            "isa_receiver_id": "RECV1",
            "transaction_type": "850",
            "webhook_partner_id": "wp1",
        }
    )
    repo.webhook_partners["wp1"] = {
        "name": "Test",
        "url": "https://webhook.example.com/edi",
    }

    service = DeliveryService(storage, repo, http_adapter, FakeSftpDeliveryAdapter())
    await service.deliver(trace_id)

    assert repo.api_payloads[trace_id]["status"] == "FAILED"
    assert len(http_adapter.delivered) == 1
