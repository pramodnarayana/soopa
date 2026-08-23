import asyncio
import io

import paramiko
import edi.core.patches.paramiko  # noqa: F401 — applies legacy ssh-rsa patch on import
import structlog

from edi.ports.outbound.sftp_tester import SftpTesterPort

logger = structlog.get_logger(__name__)


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
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 - test connection accepts any host key

            connect_kwargs = {
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
                except Exception:  # noqa: BLE001
                    key_io.seek(0)
                    pkey = paramiko.Ed25519Key.from_private_key(key_io)
                connect_kwargs["pkey"] = pkey
            elif password:
                connect_kwargs["password"] = password
            else:
                return False, "Must provide either a password or a client key."

            client.connect(**connect_kwargs)  # type: ignore[arg-type]
            sftp = client.open_sftp()

            return True, None
        except Exception as e:
            logger.exception("SSH Connection failed for %s:%s", host, port)
            return False, str(e) or repr(e)
        finally:
            if sftp:
                sftp.close()
            if client:
                client.close()
