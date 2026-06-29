from typing import Protocol


class SftpDeliveryPort(Protocol):
    """
    Interface for performing outbound SFTP transfers.
    """

    async def deliver(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        """Uploads the payload to the specified SFTP server."""
        ...
