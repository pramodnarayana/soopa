from typing import Protocol


class SftpTesterPort(Protocol):
    async def test_connection(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        client_key_string: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Tests an SFTP connection.
        Returns a tuple: (success: bool, error_reason: str | None)
        """
        ...
