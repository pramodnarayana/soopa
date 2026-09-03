import json
from typing import cast

from seedwork.domain.types import JsonValue

from edi.ports.outbound.storage_port import StoragePort


async def hydrate_edi_data(
    storage: StoragePort, storage_uri: str | None, inline_data: str | None
) -> str | None:
    if not storage_uri:
        return inline_data

    try:
        payload = await storage.download(storage_uri)
        return payload.decode("utf-8")
    except Exception:  # noqa: BLE001 - storage adapters expose provider-specific failures
        return ""


async def hydrate_json_payload(
    storage: StoragePort, storage_uri: str | None, inline_payload: JsonValue | None
) -> JsonValue | None:
    if not storage_uri:
        return inline_payload

    try:
        payload = await storage.download(storage_uri)
        return cast(JsonValue, json.loads(payload))
    except Exception:  # noqa: BLE001 - storage adapters expose provider-specific failures
        return {}
