from unittest.mock import MagicMock, patch

import pytest

from edi.adapters.outbound.pipeline.sftp import ParamikoSftpClient


@pytest.mark.asyncio
@patch("edi.adapters.outbound.pipeline.sftp.paramiko.SSHClient")
@patch("edi.adapters.outbound.pipeline.sftp.paramiko.RSAKey")
async def test_paramiko_sftp_delivery_adapter(mock_rsa_key, mock_ssh_client_class):
    # Stub out host key parsing
    mock_parsed_key = MagicMock()
    mock_rsa_key.return_value = mock_parsed_key

    mock_client = MagicMock()
    mock_ssh_client_class.return_value = mock_client

    mock_sftp = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp

    adapter = ParamikoSftpClient()

    await adapter.deliver(
        host="sftp.example.com",
        port=22,
        username="user",
        # Safe: dummy password for unit test mocking
        password="password",  # noqa: S106
        remote_path="/upload/",
        filename="test.txt",
        payload=b"test payload",
        host_key="ssh-rsa AAAA",
        client_key=None,
    )

    # SSHClient was instantiated and connected
    mock_ssh_client_class.assert_called_once()
    mock_client.connect.assert_called_once()
    call_kwargs = mock_client.connect.call_args.kwargs
    assert call_kwargs["hostname"] == "sftp.example.com"
    assert call_kwargs["port"] == 22
    assert call_kwargs["username"] == "user"
    # Safe: dummy password for unit test mocking
    assert call_kwargs["password"] == "password"  # noqa: S105

    # SFTP session was opened and the file was uploaded
    mock_client.open_sftp.assert_called_once()
    mock_sftp.putfo.assert_called_once()
    _, path = mock_sftp.putfo.call_args.args
    assert path == "/upload/test.txt"
