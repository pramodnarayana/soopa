import structlog

logger = structlog.get_logger(__name__)
from seedwork.domain.types import JsonValue
from seedwork.json_extractor import GenericJsonExtractor

from edi.domain.metadata.extractors import EXTRACTOR_CONFIG


class MetadataExtractorService:
    """
    Service responsible for dynamically extracting business fields from a structured JSON
    payload using JSONPath expressions defined in the configuration.
    """

    def __init__(self, config: dict[str, dict[str, str]] | None = None) -> None:
        self.config: dict[str, dict[str, str]] = config or EXTRACTOR_CONFIG

    def extract(self, transaction_type: str, payload: JsonValue) -> dict[str, JsonValue]:
        """
        Extracts metadata fields from the payload (dict or list) based on the transaction type.
        Returns a flat dictionary of extracted key-value strings or lists of strings.
        """
        if not transaction_type or transaction_type not in self.config:
            logger.debug(
                "No extractor configuration found for transaction type: {transaction_type}",
                transaction_type=transaction_type,
            )
            return {}

        return GenericJsonExtractor.extract_payload(self.config[transaction_type], payload)
