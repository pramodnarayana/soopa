from typing import Protocol


class VaultServicePort(Protocol):
    def get_host_private_key(self) -> bytes: ...

    def get_host_certificate(self) -> bytes: ...
