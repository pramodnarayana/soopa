"""Port contract for extracting raw source payloads into typed ExtractionBatch instances."""

from __future__ import annotations

from typing import Protocol

from seedwork.domain.types import JsonValue

from ip.engine.domain.replication.extractor import DeclarativeRecordExtractor
from ip.engine.domain.replication.stream_definition import ExtractionBatch, StreamDefinition


class RecordExtractorPort(Protocol):
    """Pure strategy extracting raw inbound payloads into validated records and rejections."""

    def extract(self, raw: JsonValue, stream: StreamDefinition) -> ExtractionBatch:
        """Extracts records from raw JSON payload according to the stream definition."""
        ...


class RecordExtractorRegistry:
    """Registry managing pluggable RecordExtractorPort strategies."""

    def __init__(self) -> None:
        self._extractors: dict[str, RecordExtractorPort] = {
            "declarative": DeclarativeRecordExtractor(),
        }

    def register(self, extractor_id: str, extractor: RecordExtractorPort) -> None:
        self._extractors[extractor_id] = extractor

    def get(self, extractor_id: str) -> RecordExtractorPort:
        if extractor_id in self._extractors:
            return self._extractors[extractor_id]
        return self._extractors["declarative"]
