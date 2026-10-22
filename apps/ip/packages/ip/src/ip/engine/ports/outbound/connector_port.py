"""Segregated port protocols (ISP) for application connectors in the Integration Platform."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.ports.types import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    WriteRecordCommand,
    WriteResultDTO,
)


class ConnectorMetadataPort(Protocol):
    """Port for connector specification, health check, and schema discovery."""

    @property
    @abstractmethod
    def app_id(self) -> str:
        """Unique identifier of the external application (e.g. 'itron_mdm', 'sftp')."""
        ...

    @abstractmethod
    def spec(self) -> AppSpecDTO:
        """Returns dynamic property schema and configuration parameters needed by the connector."""
        ...

    @abstractmethod
    async def check(
        self,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> ConnectionCheckResultDTO:
        """Validates connectivity and credentials with the external system."""
        ...

    @abstractmethod
    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> DiscoveredCatalogDTO:
        """Introspects the external system to discover available objects and schemas."""
        ...


class SourceConnectorPort(ConnectorMetadataPort, Protocol):
    """Hexagonal outbound port for source (ingress/read) connectors."""

    @abstractmethod
    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        """Lists discrete object identifiers from a stream for browsing or AI agent inspection."""
        ...

    @abstractmethod
    def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        """Streams records asynchronously from the external system."""
        ...


class DestinationConnectorPort(ConnectorMetadataPort, Protocol):
    """Hexagonal outbound port for destination (egress/write) connectors."""

    @abstractmethod
    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        """Writes/mutates a record in the external application."""
        ...


class ConnectorPort(SourceConnectorPort, DestinationConnectorPort, Protocol):
    """Full bidirectional connector port combining SourceConnectorPort and DestinationConnectorPort."""

    ...
