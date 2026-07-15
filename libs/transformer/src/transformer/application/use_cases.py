from dataclasses import dataclass
from typing import Protocol

from transformer.application.ports import EDITransformerPort
from transformer.domain.models import ParsedEdiPayload


class StoragePort(Protocol):
    """Outbound port for fetching raw EDI payloads from S3/Storage."""

    async def get_raw_payload(self, s3_uri: str) -> bytes: ...


class ParsedEdiRepositoryPort(Protocol):
    """Outbound port for saving the parsed JSON result to the database."""

    async def save_parsed_payload(self, trace_id: str, payload: ParsedEdiPayload) -> None:
        """
        Save parsed payload idempotently by trace_id.
        Implementation should upsert or ignore duplicates to handle SQS retries safely.
        Repository implementation must enforce a uniqueness constraint on trace_id.
        """
        ...


@dataclass
class ProcessInboundEdiUseCase:
    """
    Core business use case for translating raw inbound EDI into application JSON.
    It orchestrates the retrieval of raw data, the execution of the EDI engine
    (Bots), and the persistence of the parsed data.
    """

    storage_port: StoragePort
    transformer_port: EDITransformerPort
    repository_port: ParsedEdiRepositoryPort

    async def execute(self, trace_id: str, s3_uri: str) -> ParsedEdiPayload:
        # 1. Fetch raw payload bytes
        raw_edi_bytes = await self.storage_port.get_raw_payload(s3_uri)

        # 2. Execute translation via Anti-Corruption Layer (e.g. Bots EDI)
        parsed_payload = await self.transformer_port.transform(raw_edi_bytes)

        # 3. Save the parsed output to the database
        await self.repository_port.save_parsed_payload(trace_id, parsed_payload)

        return parsed_payload
