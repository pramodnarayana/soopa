from typing import Protocol


class FieldEncryptionPort(Protocol):
    def encrypt(self, data: str) -> str: ...
