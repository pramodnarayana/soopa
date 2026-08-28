from enum import StrEnum


class TransactionDirection(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class TransactionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class EdiConnectionType(StrEnum):
    AS2 = "AS2"
    API = "API"
    SFTP = "SFTP"
