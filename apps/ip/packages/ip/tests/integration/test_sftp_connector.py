"""Narrow integration tests for SftpConnector against local Docker SFTP server (127.0.0.1:2222)."""

from __future__ import annotations

import pytest
from ip.engine.adapters.outbound.connectors.sftp_connector import SftpConnector
from ip.engine.domain.exceptions import SftpConnectionError
from ip.engine.ports.types import WriteRecordCommand
from seedwork import generate_id
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_sftp_connector_check_success_against_local_sftp() -> None:
    connector = SftpConnector(timeout_seconds=5.0, allow_local=True)
    result = await connector.check(
        public_config={"host": "127.0.0.1", "port": 2222, "base_directory": "/upload"},
        credentials={"username": "testuser", "password": "pass"},
    )
    assert result.success is True
    assert result.status == "SUCCEEDED"
    assert "verified" in str(result.message)


@pytest.mark.asyncio
async def test_sftp_connector_check_failure_with_invalid_credentials() -> None:
    connector = SftpConnector(timeout_seconds=5.0, allow_local=True)
    result = await connector.check(
        public_config={"host": "127.0.0.1", "port": 2222},
        credentials={"username": "testuser", "password": "wrong_password"},
    )
    assert result.success is False
    assert result.status == "FAILED"
    assert isinstance(result.error, SftpConnectionError)


@pytest.mark.asyncio
async def test_sftp_connector_write_and_read_stream_against_local_sftp() -> None:
    connector = SftpConnector(timeout_seconds=5.0, allow_local=True)
    public_config: JsonDict = {"host": "127.0.0.1", "port": 2222, "base_directory": "/upload"}
    credentials: JsonDict = {"username": "testuser", "password": "pass"}
    filename = f"{generate_id(DomainIdPrefix.IP_INBOUND_RECORD.value)}.csv"

    write_res = await connector.write_record(
        stream_name="files",
        command=WriteRecordCommand(
            stream_name="files",
            operation="CREATE",
            record_id=filename,
            payload={"filename": filename, "content": "meter_id,kwh\nMTR-01,42.5\n"},
        ),
        public_config=public_config,
        credentials=credentials,
    )
    assert write_res.success is True
    assert write_res.record_id == filename
    assert write_res.destination_id == f"/upload/{filename}"

    records = [
        r
        async for r in connector.read_stream(
            stream_name="files",
            public_config=public_config,
            credentials=credentials,
            limit=100,
        )
    ]
    found_ids = [r.record_id for r in records]
    assert filename in found_ids


@pytest.mark.asyncio
async def test_sftp_connector_read_stream_returns_empty_on_connection_failure() -> None:
    connector = SftpConnector(timeout_seconds=1.0, allow_local=True)
    records = [
        r
        async for r in connector.read_stream(
            stream_name="files",
            public_config={"host": "127.0.0.1", "port": 59998},
            credentials={"username": "testuser", "password": "pass"},
        )
    ]
    assert records == []
