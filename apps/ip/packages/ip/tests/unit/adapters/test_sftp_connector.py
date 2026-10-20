"""Unit tests for the native SftpConnector."""

from __future__ import annotations

import pytest
from ip.adapters.outbound.connectors.sftp_connector import SftpConnector


class _FakeSftpSSHClient:
    def close(self) -> None:
        pass


class _FakeSuccessSftpConnector(SftpConnector):
    def _create_client(self, public_config, credentials):
        return _FakeSftpSSHClient()


class _FakeFailingSftpConnector(SftpConnector):
    def _create_client(self, public_config, credentials):
        raise OSError("Connection refused")


def test_sftp_connector_spec() -> None:
    connector = SftpConnector()
    spec = connector.spec()
    assert spec["appId"] == "sftp"
    assert spec["displayName"] == "SFTP File Gateway"
    assert spec["category"] == "STORAGE"
    prop_names = [p["name"] for p in spec["properties"]]
    assert "host" in prop_names
    assert "port" in prop_names
    assert "username" in prop_names


@pytest.mark.asyncio
async def test_sftp_connector_check_success() -> None:
    connector = _FakeSuccessSftpConnector()
    result = await connector.check(
        public_config={"host": "sftp.example.com", "port": 22},
        credentials={"username": "user", "password": "pass"},
    )
    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "verified" in str(result.message)


@pytest.mark.asyncio
async def test_sftp_connector_check_failure() -> None:
    connector = _FakeFailingSftpConnector()
    result = await connector.check(
        public_config={"host": "sftp.example.com", "port": 22},
        credentials={"username": "user", "password": "wrong"},
    )
    assert result.success is False
    assert result.status == "FAILED"
    assert "Connection refused" in str(result.message)


@pytest.mark.asyncio
async def test_sftp_connector_discover() -> None:
    connector = SftpConnector()
    catalog = await connector.discover(
        connection_id="conn_sftp_123",
        public_config={"host": "sftp.example.com"},
        credentials={"username": "user"},
    )
    assert catalog.connection_id == "conn_sftp_123"
    assert len(catalog.streams) >= 1
    stream_names = [s.name for s in catalog.streams]
    assert "files" in stream_names
