from enum import StrEnum


class Channel(StrEnum):
    EMAIL = "EMAIL"
    IN_APP = "IN_APP"
    SLACK = "SLACK"


__all__ = ["Channel"]
