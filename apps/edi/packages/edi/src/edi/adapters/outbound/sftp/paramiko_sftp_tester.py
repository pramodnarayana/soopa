"""SFTP Diagnostic Connectivity Adapter delegating to centralized platform sftp package."""

from __future__ import annotations

from sftp import SftpConnectionConfig, test_sftp_connection

from edi.ports.outbound.sftp_tester import SftpTesterPort


class ParamikoSftpTesterAdapter(SftpTesterPort):
    """Adapter testing SFTP connectivity using centralized platform sftp client."""

    def __init__(self, allow_local: bool = False) -> None:
        self._allow_local = allow_local

    async def test_connection(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        client_key_string: str | None = None,
    ) -> tuple[bool, str | None]:
        config = SftpConnectionConfig(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=client_key_string,
            allow_local=self._allow_local,
            timeout_seconds=10.0,
        )
        return await test_sftp_connection(config)
