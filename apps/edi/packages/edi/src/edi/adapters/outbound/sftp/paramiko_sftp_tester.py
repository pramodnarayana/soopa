import asyncio
import io
import ipaddress
import socket
import typing

import paramiko
import structlog

from edi.ports.outbound.sftp_tester import SftpTesterPort

logger = structlog.get_logger(__name__)


class HostValidationError(Exception):
    """Raised when a host fails SSRF validation during SFTP connection setup."""


def _resolve_and_validate_host(host: str, port: int) -> list[str]:
    """
    Resolve the host using getaddrinfo (covers both IPv4 and IPv6) and validate
    that every returned address is globally routable.

    Returns the full list of validated IP address strings in resolution order so
    that the caller can attempt each candidate in turn — preventing DNS rebinding
    between the validation step and the actual socket open.

    Raises HostValidationError if any resolved address is non-global or if
    resolution fails.
    """
    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HostValidationError(f"Failed to resolve host '{host}': {exc}") from exc

    if not addr_infos:
        raise HostValidationError(f"No addresses resolved for host '{host}'")

    validated_ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        # sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise HostValidationError(
                f"Unparsable IP address '{ip_str}' for host '{host}'"
            ) from exc

        if not ip.is_global:
            raise HostValidationError(
                f"SSRF blocked: host '{host}' resolved to non-global address '{ip_str}'"
            )

        validated_ips.append(ip_str)

    return validated_ips


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
        try:
            # Resolve and validate all candidates immediately before opening the socket.
            # Iterating via validated IPs (not the original hostname) prevents DNS
            # rebinding between this check and the actual TCP handshake.
            candidates = _resolve_and_validate_host(host, port)
        except HostValidationError as e:
            logger.warning("sftp_ssrf_blocked", host=host, port=port, reason=str(e))
            return False, str(e)

        # Build the key material once, outside the per-candidate loop.
        pkey: paramiko.PKey | None = None
        if client_key_string:
            key_io = io.StringIO(client_key_string)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_io)
            except (paramiko.SSHException, ValueError):
                key_io.seek(0)
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(key_io)
                except (paramiko.SSHException, ValueError) as e:
                    return False, f"Malformed or unsupported SSH key: {e}"
        elif not password:
            return False, "Must provide either a password or a client key."

        last_error: str | None = None
        for candidate_ip in candidates:
            client = None
            sftp = None
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(DiagnosticHostKeyPolicy())

                connect_kwargs: ParamikoConnectKwargs = {
                    "hostname": candidate_ip,
                    "port": port,
                    "username": username,
                    "look_for_keys": False,
                    "allow_agent": False,
                    "timeout": 10,
                    "disabled_algorithms": {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]},
                }

                if pkey is not None:
                    connect_kwargs["pkey"] = pkey
                elif password:
                    connect_kwargs["password"] = password

                client.connect(**connect_kwargs)
                sftp = client.open_sftp()
                return True, None
            except (
                paramiko.AuthenticationException,
                paramiko.SSHException,
                paramiko.ssh_exception.NoValidConnectionsError,
                OSError,
            ) as e:
                last_error = str(e) or repr(e)
                logger.warning(
                    "sftp_candidate_connection_failed",
                    host=host,
                    candidate_ip=candidate_ip,
                    port=port,
                    reason=last_error,
                )
            finally:
                if sftp:
                    sftp.close()
                if client:
                    client.close()

        # All candidates exhausted — log once and return the last error.
        # logger.error (not logger.exception) is correct here: we are outside any active
        # except block, so logger.exception would capture a spurious 'NoneType: None' traceback.
        logger.error(
            "sftp_diagnostic_connection_failed",
            host=host,
            port=port,
            candidates=candidates,
        )
        return False, last_error
