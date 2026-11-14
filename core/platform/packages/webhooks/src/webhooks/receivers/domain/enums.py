"""Domain enumerations for webhook ingress receivers."""

from enum import StrEnum


class VerificationStrategy(StrEnum):
    """Supported cryptographic and perimeter authentication mechanisms for incoming webhooks."""

    HMAC_SHA256 = "HMAC_SHA256"
    BEARER_TOKEN = "BEARER_TOKEN"  # noqa: S105 - Ingress strategy enum identifier, not a hardcoded secret
    SHARED_HEADER_SECRET = "SHARED_HEADER_SECRET"  # noqa: S105 - Ingress strategy enum identifier, not a hardcoded secret
    QUERY_TOKEN = "QUERY_TOKEN"  # noqa: S105 - Ingress strategy enum identifier, not a hardcoded secret
    MUTUAL_TLS = "MUTUAL_TLS"
    PUBLIC_UNAUTHENTICATED = "PUBLIC_UNAUTHENTICATED"


class PayloadSemantic(StrEnum):
    """Semantic modality of an inbound webhook event.

    DATA: Data plane records (e.g. meter telemetry, financial transactions) traversing L1 -> L2 -> L3 -> L5.
    COMMAND: Instructions (e.g. historical extract request, emergency disconnect) bypassing L2/L3 to L4 Orchestrator.
    """

    DATA = "DATA"
    COMMAND = "COMMAND"
