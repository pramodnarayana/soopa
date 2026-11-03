"""UCP Model Constants and Identifier Prefixes."""

from enum import StrEnum


class UcpModelIdPrefix(StrEnum):
    """Domain-specific ID prefixes for UCP persistent models."""

    OUTBOX = "ucp_ob"
    APP = "ucp_app"
    SHARD = "ucp_shard"


__all__ = ["UcpModelIdPrefix"]
