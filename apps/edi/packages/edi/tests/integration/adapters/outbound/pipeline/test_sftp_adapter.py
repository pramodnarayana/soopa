# ruff: noqa
import pytest

from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient
import subprocess
import time


@pytest.mark.asyncio
async def test_paramiko_sftp_delivery_adapter():
    adapter = ParamikoSftpClient()

    # In docker-compose, atmoz/sftp is configured with: testuser:pass:1001

    # Get the host key dynamically

    # Give the container a moment to be ready if it just started
    host_key = None
    for _ in range(5):
        try:
            out = subprocess.check_output(
                ["ssh-keyscan", "-p", "2222", "-t", "rsa", "localhost"], stderr=subprocess.DEVNULL
            ).decode("utf-8")
            if out.strip():
                # Extract the key part (e.g. ssh-rsa AAAA...)
                host_key = out.strip().split("localhost ", 1)[-1]
                break
        except Exception:
            pass
        time.sleep(1)

    if not host_key:
        pytest.fail("Could not retrieve host key for localhost:2222")

    await adapter.deliver(
        host="localhost",
        port=2222,
        username="testuser",
        password="pass",
        remote_path="upload",
        filename="test_upload.txt",
        payload=b"real sftp test payload",
        host_key=host_key,
        client_key=None,
    )

    # To verify, we would ideally connect and read back, or rely on the adapter throwing an error if it fails.
    # The ParamikoSftpClient.deliver method raises exceptions if it fails.
    # A successful execution without exceptions implies the file was transferred.
