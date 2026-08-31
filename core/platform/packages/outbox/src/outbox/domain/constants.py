from enum import StrEnum


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    RESERVED = "RESERVED"
    SUCCESS = "SUCCESS"
