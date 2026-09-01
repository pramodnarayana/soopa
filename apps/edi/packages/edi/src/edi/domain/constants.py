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


class EdiIdPrefix(StrEnum):
    CP_OUTBOX = "edi_cp_ob"
    DP_OUTBOX = "edi_dp_ob"
    AS2_SERVER = "edi_as2"
    AS2_PARTNER = "edi_as2p"
    SFTP_PARTNER = "edi_sftp"
    WEBHOOK = "edi_dp_wh"
    INBOUND_ROUTE = "edi_inbrt"
    OUTBOUND_HEADER = "edi_outhdr"
    OUTBOUND_ROUTE = "edi_outrt"
    EDI_MESSAGE = "edi_msg"
    EDI_JSON = "edi_json"
    API_GATEWAY = "edi_apigw"
