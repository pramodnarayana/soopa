import pytest

from edi.adapters.outbound.database.payload_hydration import (
    hydrate_edi_data,
    hydrate_json_payload,
)


class FakeStorage:
    def __init__(self, payloads: dict[str, bytes]) -> None:
        self.payloads = payloads

    async def download(self, uri: str) -> bytes:
        return self.payloads[uri]

    async def upload(self, payload: bytes, key_prefix: str, file_name: str) -> str:
        uri = f"s3://bucket/{key_prefix}/{file_name}"
        self.payloads[uri] = payload
        return uri


@pytest.mark.asyncio
async def test_hydration_preserves_inline_payloads_without_storage_uri() -> None:
    storage = FakeStorage({})

    assert await hydrate_edi_data(storage, None, "inline edi") == "inline edi"
    assert await hydrate_json_payload(storage, None, {"inline": True}) == {"inline": True}


@pytest.mark.asyncio
async def test_hydration_resolves_storage_payloads() -> None:
    storage = FakeStorage(
        {
            "s3://bucket/message": b"ISA*00*",
            "s3://bucket/json": b'{"shipment_id": "SHP-1"}',
        }
    )

    assert await hydrate_edi_data(storage, "s3://bucket/message", None) == "ISA*00*"
    assert await hydrate_json_payload(storage, "s3://bucket/json", None) == {"shipment_id": "SHP-1"}


@pytest.mark.asyncio
async def test_hydration_returns_empty_payload_when_storage_cannot_be_resolved() -> None:
    storage = FakeStorage({})

    assert await hydrate_edi_data(storage, "s3://bucket/missing", None) == ""
    assert await hydrate_json_payload(storage, "s3://bucket/missing", None) == {}
