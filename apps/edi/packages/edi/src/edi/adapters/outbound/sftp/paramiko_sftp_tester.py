import asyncio
import io
import ipaddress
import socket
import typing

import paramiko
import structlog

from edi.ports.outbound.sftp_tester import SftpTesterPort

logger = structlog.get_logger(__name__)


def _resolve_and_validate_host(host: str, port: int) -> str:
    """
    Resolve the host using getaddrinfo (covers both IPv4 and IPv6) and validate
    that every returned address is globally routable.

    Returns the string representation of the first validated IP address so that
    Paramiko connects directly to it — preventing DNS rebinding between the
    validation step and the actual socket open.

    Raises ValueError if any resolved address is non-global or if resolution fails.
    """
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Failed to resolve host '{host}': {exc}") from exc

    if not addr_infos:
        raise ValueError(f"No addresses resolved for host '{host}'")

    validated_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        # sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise ValueError(f"Unparsable IP address '{ip_str}' for host '{host}'") from exc

        if not ip.is_global:
            raise ValueError(
                f"SSRF blocked: host '{host}' resolved to non-global address '{ip_str}'"
            )

        if validated_ip is None:
            validated_ip = ip_str

    assert validated_ip is not None  # guaranteed by the `if not addr_infos` guard above
    return validated_ip


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
            # Resolve and validate immediately before opening the socket.
            # Connecting via the returned IP (not the original hostname) prevents
            # DNS rebinding between this check and the actual TCP handshake.
            validated_ip = _resolve_and_validate_host(host, port)

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(DiagnosticHostKeyPolicy())

            connect_kwargs: ParamikoConnectKwargs = {
                "hostname": validated_ip,
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
        except ValueError as e:
            # SSRF validation failure — surface as a clear failure reason
            logger.warning("sftp_ssrf_blocked", host=host, port=port, reason=str(e))
            return False, str(e)
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
