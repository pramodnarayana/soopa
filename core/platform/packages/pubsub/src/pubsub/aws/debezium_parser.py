import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DebeziumPayloadParser:
    """
    Centralized utility to safely extract and parse payloads from Debezium/SQS events.
    Debezium's pgoutput maps PostgreSQL JSONB columns to string types. This parser
    ensures they are safely deserialized back into Python dictionaries.
    """

    @staticmethod
    def extract_payload(
        body: dict[str, Any], payload_key: str = "payload"
    ) -> dict[str, Any] | None:
        if not isinstance(body, dict):
            return None

        payload = body.get(payload_key)

        # Debezium serializes PostgreSQL JSONB as an escaped string.
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                logger.warning("debezium_parser.json_decode_failed", payload=payload)
                return None

        if not isinstance(payload, dict):
            return None

        return payload
