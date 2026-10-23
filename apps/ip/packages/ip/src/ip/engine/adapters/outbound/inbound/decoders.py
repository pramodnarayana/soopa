"""Payload decoders converting incoming HTTP byte streams into structured JSON/object trees."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import structlog
from ip.engine.domain.exceptions import InboundPayloadDecodeError, IpError, Result
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from seedwork.domain.types import JsonValue

logger = structlog.get_logger(__name__)


class StandardInboundPayloadDecoder(InboundPayloadDecoderPort):
    """MIME-aware payload decoder handling JSON, form-encoded, and text streams."""

    def decode(
        self,
        *,
        content_type: str,
        raw_body: bytes,
    ) -> Result[JsonValue, IpError]:
        clean_ct = content_type.split(";")[0].strip().lower()

        try:
            # 1. JSON
            if clean_ct in ("application/json", "text/json") or clean_ct.endswith("+json"):
                text = raw_body.decode("utf-8")
                if not text.strip():
                    return Result.ok({})
                parsed: JsonValue = json.loads(text)
                return Result.ok(parsed)

            # 2. Form-encoded
            if clean_ct in (
                "application/x-www-form-urlencoded",
                "multipart/form-data",
            ):
                text = raw_body.decode("utf-8")
                raw_qs = parse_qs(text, keep_blank_values=True)
                # Flatten single-item lists
                flattened: dict[str, JsonValue] = {
                    k: v[0] if len(v) == 1 else list(v) for k, v in raw_qs.items()
                }
                return Result.ok(flattened)

            # 3. Default text / fallback attempt to parse as JSON if it looks like JSON
            text = raw_body.decode("utf-8")
            trimmed = text.strip()
            if trimmed.startswith(("{", "[")):
                try:
                    fallback_json: JsonValue = json.loads(trimmed)
                    return Result.ok(fallback_json)
                except json.JSONDecodeError:
                    pass

            return Result.ok({"raw_text": text})

        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            logger.error(
                "inbound_payload_decode_failed",
                content_type=content_type,
                reason=str(exc),
            )
            return Result.fail(
                InboundPayloadDecodeError(
                    message=f"Failed to decode payload with Content-Type '{content_type}': {exc}"
                )
            )
