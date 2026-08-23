from typing import Any

import structlog
from jsonpath_ng import parse  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)

# Enterprise configuration mapping transaction types to JSONPath expressions
# Using recursive descendant paths ($..) to extract fields accurately regardless
# of whether the JSON is wrapped in ISA/GS envelopes (Inbound) or is just a bare transaction (Outbound).
EXTRACTOR_CONFIG: dict[str, dict[str, str]] = {
    "850": {
        "po_number": "$..BEG.BEG03",
        "po_date": "$..BEG.BEG05",
        "business_reference": "$..BEG.BEG03",
    },
    "810": {
        "invoice_number": "$..BIG.BIG02",
        "po_number": "$..BIG.BIG04",
        "business_reference": "$..BIG.BIG02",
    },
    "204": {
        "load_number": "$..B2.B204",
        "business_reference": "$..B2.B204",
    },
    "990": {
        "load_number": "$..B1.B102",
        "business_reference": "$..B1.B102",
    },
    "214": {
        "load_number": "$..B10.B1002",
        "business_reference": "$..B10.B1002",
    },
    "210": {
        "invoice_number": "$..B3.B302",
        "business_reference": "$..B3.B302",
    },
    "997": {
        "group_control_number": "$..AK1.AK102",
        "business_reference": "$..AK1.AK102",
    },
}


class MetadataExtractorService:
    """
    Service responsible for dynamically extracting business fields from a structured JSON
    payload using JSONPath expressions defined in the configuration.
    """

    def __init__(self, config: dict[str, dict[str, str]] | None = None) -> None:
        self.config = config or EXTRACTOR_CONFIG
        # Pre-compile the JSONPath expressions for performance
        self.compiled_config: dict[str, dict[str, Any]] = {}
        self._compile_config()

    def _compile_config(self) -> None:
        for tx_type, paths in self.config.items():
            self.compiled_config[tx_type] = {}
            for field_name, json_path in paths.items():
                try:
                    self.compiled_config[tx_type][field_name] = parse(json_path)
                except Exception:
                    logger.exception(
                        "Failed to compile JSONPath '%s' for %s.%s",
                        json_path,
                        tx_type,
                        field_name,
                    )

    def extract(self, transaction_type: str, payload: dict[str, Any]) -> dict[str, str]:
        """
        Extracts metadata fields from the payload based on the transaction type.
        Returns a flat dictionary of extracted key-value strings.
        """
        if not transaction_type or transaction_type not in self.compiled_config:
            logger.debug(
                "No extractor configuration found for transaction type: {transaction_type}",
                transaction_type=transaction_type,
            )
            return {}

        extracted_metadata: dict[str, str] = {}
        extractors = self.compiled_config[transaction_type]

        for field_name, jsonpath_expr in extractors.items():
            try:
                matches = jsonpath_expr.find(payload)
                if matches:
                    # We take the first match's value as a string
                    val = matches[0].value
                    if val is not None:
                        extracted_metadata[field_name] = str(val)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Error extracting field '%s' for type '%s'",
                    field_name,
                    transaction_type,
                )

        return extracted_metadata
