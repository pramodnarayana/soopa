import asyncio
import io
import logging

import paramiko
from pipeline.ports.sftp import SftpDeliveryPort

logger = logging.getLogger(__name__)


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
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        await asyncio.to_thread(
            self._deliver_sync, host, port, username, password, remote_path, filename, payload
        )

    def _deliver_sync(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        remote_path: str,
        filename: str,
        payload: bytes,
    ) -> None:
        transport = None
        sftp = None
        try:
            # We skip host key verification for simplicity here,
            # but in production, we should load known_hosts or strictly verify.
            transport = paramiko.Transport((host, port))
            transport.connect(username=username, password=password)
            sftp = paramiko.SFTPClient.from_transport(transport)

            if not sftp:
                raise RuntimeError("Failed to create SFTP client from transport")

            target_file = f"{remote_path.rstrip('/')}/{filename}" if remote_path else filename

            # Use putfo for file-like object
            with io.BytesIO(payload) as fl:
                sftp.putfo(fl, target_file)

            logger.info(f"Successfully uploaded {filename} to {host}:{port}{'/' + target_file}")

        except Exception as e:
            logger.error(f"SFTP upload failed for {host}:{port}: {e}")
            raise RuntimeError(f"SFTP Delivery failed: {e}") from e
        finally:
            if sftp:
                sftp.close()
            if transport:
                transport.close()
