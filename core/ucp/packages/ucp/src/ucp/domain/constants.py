from enum import StrEnum


class DomainIdPrefix(StrEnum):
    APP = "ucp_app"
    SHARD = "ucp_shard"
    OUTBOX = "ucp_ob"
    WEBHOOK = "ucp_wh"
