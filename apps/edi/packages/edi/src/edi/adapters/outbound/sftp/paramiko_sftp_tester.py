import asyncio
import io
import typing

import paramiko
import structlog

from edi.ports.outbound.sftp_tester import SftpTesterPort

logger = structlog.get_logger(__name__)


class ParamikoConnectKwargs(typing.TypedDict, total=False):
    hostname: str
    port: int
    username: str
    password: str
    look_for_keys: bool
    allow_agent: bool
    timeout: int
    disabled_algorithms: dict[str, list[str]]
    pkey: paramiko.PKey


class DiagnosticHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """
    Silently accepts any host key during diagnostic connectivity tests.

    This is intentionally permissive: the adapter's sole responsibility is
    to verify that authentication credentials are valid, not to validate
    server identity. Host-key pinning is a concern for production SFTP
    data transfers, not for one-off diagnostic pings.
    """

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        pass


class ParamikoSftpTesterAdapter(SftpTesterPort):
    async def test_connection(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        client_key_string: str | None = None,
    ) -> tuple[bool, str | None]:
        return await asyncio.to_thread(
            self._test_connection_sync, host, port, username, password, client_key_string
        )

    def _test_connection_sync(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None,
        client_key_string: str | None,
    ) -> tuple[bool, str | None]:
        client = None
        sftp = None
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(DiagnosticHostKeyPolicy())

            connect_kwargs: ParamikoConnectKwargs = {
                "hostname": host,
                "port": port,
                "username": username,
                "look_for_keys": False,
                "allow_agent": False,
                "timeout": 10,
                "disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
            }

            if client_key_string:
                key_io = io.StringIO(client_key_string)
                try:
                    pkey: paramiko.PKey = paramiko.RSAKey.from_private_key(key_io)
                except (paramiko.SSHException, ValueError):
                    key_io.seek(0)
                    pkey = paramiko.Ed25519Key.from_private_key(key_io)
                connect_kwargs["pkey"] = pkey
            elif password:
                connect_kwargs["password"] = password
            else:
                return False, "Must provide either a password or a client key."

            client.connect(**connect_kwargs)
            sftp = client.open_sftp()

            return True, None
        except (
            paramiko.AuthenticationException,
            paramiko.SSHException,
            paramiko.ssh_exception.NoValidConnectionsError,
            OSError,
        ) as e:
            logger.exception("sftp_diagnostic_connection_failed", host=host, port=port)
            return False, str(e) or repr(e)
        finally:
            if sftp:
                sftp.close()
            if client:
                client.close()
