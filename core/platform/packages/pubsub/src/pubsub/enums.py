from enum import StrEnum


class ConsumerAction(StrEnum):
    ACK = "ACK"
    NACK = "NACK"
    DLQ = "DLQ"
