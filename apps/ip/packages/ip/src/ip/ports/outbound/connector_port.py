"""Port protocol for application connectors in the Integration Platform."""

from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from ip.domain.types import JsonDict
from ip.ports.types import (
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    WriteRecordCommand,
    WriteResultDTO,
)


class ConnectorPort(Protocol):
    """Hexagonal outbound port implemented by all application connectors.

    Follows the 4 Airbyte-inspired core protocol primitives:
    1. spec() -> Configuration JSONSchema for forms
    2. check() -> Health & credentials test
    3. discover() -> Schema & stream introspection
    4. read_stream() / write_record() -> Stream I/O
    """

    @property
    @abstractmethod
    def app_id(self) -> str:
        """Unique identifier of the external application (e.g. 'itron_mdm', 'sftp')."""
        ...

    @abstractmethod
    def spec(self) -> JsonDict:
        """Returns JSONSchema specifying the configuration parameters needed by the connector."""
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
