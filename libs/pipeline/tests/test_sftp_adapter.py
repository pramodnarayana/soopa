from unittest.mock import MagicMock, patch

import pytest
from pipeline.adapters.sftp import ParamikoSftpDeliveryAdapter


@pytest.mark.asyncio
@patch("pipeline.adapters.sftp.paramiko.Transport")
@patch("pipeline.adapters.sftp.paramiko.SFTPClient.from_transport")
async def test_paramiko_sftp_delivery_adapter(mock_from_transport, mock_transport_class):
    mock_transport = MagicMock()
    mock_transport_class.return_value = mock_transport

    mock_sftp = MagicMock()
    mock_from_transport.return_value = mock_sftp

    adapter = ParamikoSftpDeliveryAdapter()

    await adapter.deliver(
        host="sftp.example.com",
        port=22,
        username="user",
        password="password",
        remote_path="/upload/",
        filename="test.txt",
        payload=b"test payload",
    )

    # Assert connect was called with the right parameters
    mock_transport_class.assert_called_once_with(("sftp.example.com", 22))
    mock_transport.connect.assert_called_once_with(username="user", password="password")

    # Verify open and write were called via putfo
    assert mock_sftp.putfo.call_count == 1
    args, _ = mock_sftp.putfo.call_args
    assert args[1] == "/upload/test.txt"
