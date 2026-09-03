import structlog
from jsonpath_ng.ext import parse

from seedwork.domain.types import JsonDict, JsonValue

logger = structlog.get_logger(__name__)


class GenericJsonExtractor:
    """
    Generic utility to extract metadata from JSON payloads (dict or list of dicts)
    using JSONPath expressions.
    """

    @classmethod
    def extract_payload(
        cls,
        mapping_config: dict[str, JsonValue],
        payload: JsonValue,
    ) -> dict[str, JsonValue]:
        """
        Extracts fields based on JSONPath mapping config, safely handling dicts or lists of dicts.
        Returns a dictionary mapping field_name to either a string (if one unique value found)
        or a list of strings (if multiple unique values found).
        """
        extracted_metadata: dict[str, JsonValue] = {}

        # Normalize payload to a list of dicts
        items: list[JsonDict]
        if isinstance(payload, dict):
            items = [payload]
        elif isinstance(payload, list):
            items = [item for item in payload if isinstance(item, dict)]
        else:
            return extracted_metadata

        for field, jsonpath_expr in mapping_config.items():
            try:
                # Expecting pre-compiled jsonpath_expr, but handle strings too
                if isinstance(jsonpath_expr, str):
                    expr = parse(jsonpath_expr)
                else:
                    expr = jsonpath_expr

                values: list[JsonValue] = []
                for item in items:
                    matches = expr.find(item)
                    for match in matches:
                        if match.value is not None:
                            val = str(match.value)
                            if val not in values:
                                values.append(val)
                            # First match per item wins (per test_first_match_is_used_when_multiple_matches)
                            break
                
                if len(values) == 1:
                    extracted_metadata[field] = values[0]
                elif len(values) > 1:
                    extracted_metadata[field] = values
            except Exception as e:
                logger.warning("json_extraction_failed", field=field, error=str(e))

        return extracted_metadata
