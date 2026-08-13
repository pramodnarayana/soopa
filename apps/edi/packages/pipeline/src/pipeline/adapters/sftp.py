import asyncio
import base64
import io
import logging

import paramiko
import patches.paramiko  # noqa: F401 — applies legacy ssh-rsa patch on import

from pipeline.ports.sftp import SftpDeliveryPort

logger = logging.getLogger(__name__)


def _setup_host_key(
    client: paramiko.SSHClient, host: str, port: int, host_key_string: str | None
) -> None:
    if not host_key_string:
        import logging

        logging.getLogger(__name__).warning(
            f"No host key provided for {host}. Using AutoAddPolicy (vulnerable to MITM)."
        )
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        parts = host_key_string.split()
        if len(parts) < 2:
            raise ValueError(f"Malformed host_key_string: {host_key_string}")

        key_type = parts[0]
        key_data = base64.b64decode(parts[-1])
        if "ed25519" in key_type.lower():
            parsed_key: paramiko.PKey = paramiko.Ed25519Key(data=key_data)
        elif "ecdsa" in key_type.lower():
            parsed_key = paramiko.ECDSAKey(data=key_data)
        else:
            parsed_key = paramiko.RSAKey(data=key_data)

        host_identifier = f"[{host}]:{port}" if port != 22 else host
        client.get_host_keys().add(hostname=host_identifier, keytype=key_type, key=parsed_key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())


def _parse_client_key(client_key_string: str) -> paramiko.PKey:
    key_io = io.StringIO(client_key_string)
    try:
        return paramiko.RSAKey.from_private_key(key_io)
    except Exception:  # noqa: BLE001
        key_io.seek(0)
        try:
            return paramiko.ECDSAKey.from_private_key(key_io)
        except Exception:  # noqa: BLE001
            key_io.seek(0)
            return paramiko.Ed25519Key.from_private_key(key_io)


def get_ssh_client(
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    client_key_string: str | None = None,
    host_key_string: str | None = None,
    timeout: int = 10,
    use_legacy_rsa: bool = False,
) -> paramiko.SSHClient:
    """
    Creates an enterprise-grade, configured SSHClient.
    Supports both legacy servers (ssh-rsa) and modern cryptographic algorithms.
    """
    client = paramiko.SSHClient()
    _setup_host_key(client, host, port, host_key_string)

    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "look_for_keys": False,
        "allow_agent": False,
        "timeout": timeout,
    }

    if use_legacy_rsa:
        connect_kwargs["disabled_algorithms"] = {"pubkeys": ["rsa-sha2-512", "rsa-sha2-256"]}

    if client_key_string:
        connect_kwargs["pkey"] = _parse_client_key(client_key_string)
    elif password:
        connect_kwargs["password"] = password
    else:
        raise ValueError("Must provide either a password or a client key.")

    try:
        client.connect(**connect_kwargs)  # type: ignore[arg-type]
        return client
    except Exception:
        logger.exception("SSH Connection failed for %s:%s", host, port)
        client.close()
        raise


class ParamikoSftpDeliveryAdapter(SftpDeliveryPort):
    """
    Concrete implementation of SftpDeliveryPort using paramiko.
    """

    async def deliver(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
        client_key: str | None,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        await asyncio.to_thread(
            self._deliver_sync,
            host,
            port,
            username,
            password,
            host_key,
            client_key,
            remote_path,
            filename,
            payload,
        )

    def _deliver_sync(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        host_key: str | None,
        client_key: str | None,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        client = None
        sftp = None
        try:
            if not host_key:
                raise ValueError("SFTP host_key is required for server verification")

            client = get_ssh_client(
                host=host,
                port=port,
                username=username,
                password=password,
                client_key_string=client_key,
                host_key_string=host_key,
            )

            sftp = client.open_sftp()

            if not sftp:
                raise RuntimeError("Failed to create SFTP client from transport")

            target_file = f"{remote_path.rstrip('/')}/{filename}" if remote_path else filename

            # Use putfo for file-like object
            with io.BytesIO(payload) as fl:
                sftp.putfo(fl, target_file)

            logger.info(f"Successfully uploaded {filename} to {host}:{port}{'/' + target_file}")

        except Exception as e:
            logger.exception(f"SFTP upload failed for {host}:{port}")

            raise RuntimeError(f"SFTP Delivery failed: {e}") from e
        finally:
            if sftp:
                sftp.close()
            if client:
                client.close()
