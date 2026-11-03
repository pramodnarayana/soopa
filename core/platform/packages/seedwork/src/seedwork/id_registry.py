from enum import StrEnum


class SystemIdPrefix(StrEnum):
    """
    Generic system-wide ID prefixes for shared primitives.
    Domain-specific prefixes belong in their respective bounded context's constants.py.
    """

    GENERIC = "sys_id"
    EVENT = "sys_evt"
    JOB = "sys_job"
    IDEMPOTENCY = "sys_idemp"
    OUTBOX = "sys_out"
    CLIENT = "sys_client"
    TRACE = "sys_trace"
    TX = "sys_tx"


__all__ = ["SystemIdPrefix"]
