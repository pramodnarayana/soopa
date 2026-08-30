from enum import StrEnum


class SystemIdPrefix(StrEnum):
    """
    Generic system-wide ID prefixes for shared primitives.
    Domain-specific prefixes (like tenants, users, AS2 partners) should NOT be added here.
    They belong in their respective bounded context's DomainIdPrefix.
    """

    GENERIC = "sys_id"
    EVENT = "sys_evt"
    JOB = "sys_job"
    IDEMPOTENCY = "sys_idemp"
    OUTBOX = "sys_out"
    CLIENT = "sys_client"
    TRACE = "sys_trc"
    TX = "sys_tx"
