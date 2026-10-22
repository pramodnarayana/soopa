"""Strict boundary response and read DTOs for the Integration Platform.

Re-exports canonical DTOs from ip.engine.application.dto.
"""

from __future__ import annotations

from ip.engine.application.dto import (
    AppSpecDTO,
    AppSpecResultDTO,
    CatalogAppSummaryDTO,
    ConnectionCheckResultDTO,
    ConnectionDTO,
    ConnectionOperationResultDTO,
    ConnectorPropertyDTO,
    DiscoveredCatalogDTO,
    DropdownOptionDTO,
    OAuthConfigDTO,
    RecordEnvelopeDTO,
    StreamFieldDTO,
    StreamSchemaDTO,
    WriteRecordCommand,
    WriteResultDTO,
)

__all__ = [
    "AppSpecDTO",
    "AppSpecResultDTO",
    "CatalogAppSummaryDTO",
    "ConnectionCheckResultDTO",
    "ConnectionDTO",
    "ConnectionOperationResultDTO",
    "ConnectorPropertyDTO",
    "DiscoveredCatalogDTO",
    "DropdownOptionDTO",
    "OAuthConfigDTO",
    "RecordEnvelopeDTO",
    "StreamFieldDTO",
    "StreamSchemaDTO",
    "WriteRecordCommand",
    "WriteResultDTO",
]
