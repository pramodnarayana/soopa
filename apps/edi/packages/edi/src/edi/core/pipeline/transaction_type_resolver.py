"""
Transaction Type Resolver
=========================

Domain Service: resolves the EDI transaction type from a structured JSON payload
using a deterministic, ordered cascade of well-known structural patterns.

Having this logic in a single, shared domain service guarantees DRY compliance
across all Application Use Cases that need to infer the transaction type.
"""

from collections.abc import Mapping

import structlog
from seedwork.domain.types import JsonValue

logger = structlog.get_logger(__name__)


class TransactionTypeResolver:
    """
    Pure domain service (no I/O, no external dependencies) that resolves an EDI
    transaction type from a structured JSON payload.

    Extraction cascade (first match wins):
      1. Caller-supplied explicit value — trusted, no extraction needed.
      2. Flat ``transaction_type`` field on the payload root.
      3. ``heading`` → ``transaction_set_header_ST*`` nested structure
         (supports both ``transaction_set_identifier_code`` and
         ``transaction_set_identifier_code_01``).
      4. Raw ``ST`` segment shorthand (``{"ST": {"ST01": "850", ...}}``).

    Returns ``None`` when none of the patterns match so callers can raise
    a proper domain error rather than silently defaulting to a sentinel value.
    """

    @staticmethod
    def resolve(explicit_type: str | None, payload: JsonValue) -> str | None:
        """
        Resolve the transaction type for the given payload.

        Args:
            explicit_type: Caller-supplied type (e.g. from the HTTP request body
                           or a route config). Takes precedence over all extraction.
            payload: The raw JSON payload (dict or list of dicts).

        Returns:
            The resolved transaction type string, or ``None`` if unresolvable.
        """
        if explicit_type and explicit_type.strip():
            return explicit_type.strip()

        first: object = (payload[0] if payload else None) if isinstance(payload, list) else payload

        if not isinstance(first, dict):
            return None

        return TransactionTypeResolver._extract_from_dict(first)

    @staticmethod
    def _resolve_heading_dict(payload_dict: Mapping[str, object]) -> Mapping[str, object] | None:
        heading = payload_dict.get("heading")
        if isinstance(heading, dict):
            return heading
        interchange = payload_dict.get("interchange")
        if not isinstance(interchange, dict):
            return None
        transaction_sets = interchange.get("transaction_sets")
        if not isinstance(transaction_sets, list) or not transaction_sets:
            return None
        first_set = transaction_sets[0]
        if not isinstance(first_set, dict):
            return None
        nested_heading = first_set.get("heading")
        return nested_heading if isinstance(nested_heading, dict) else None

    @staticmethod
    def _extract_st_from_heading(heading: Mapping[str, object]) -> str | None:
        for key, inner in heading.items():
            if not key.startswith("transaction_set_header_ST"):
                continue
            if isinstance(inner, dict):
                inner_val = inner.get("transaction_set_identifier_code") or inner.get(
                    "transaction_set_identifier_code_01"
                )
                if isinstance(inner_val, str) and inner_val.strip():
                    return inner_val.strip()
            break
        return None

    @staticmethod
    def _extract_from_dict(payload_dict: Mapping[str, object]) -> str | None:
        """Extract from a single payload dict using the ordered cascade."""
        val = payload_dict.get("transaction_type")
        if isinstance(val, str) and val.strip():
            return val.strip()

        heading = TransactionTypeResolver._resolve_heading_dict(payload_dict)
        if heading is not None:
            from_heading = TransactionTypeResolver._extract_st_from_heading(heading)
            if from_heading is not None:
                return from_heading

        st = payload_dict.get("ST")
        if isinstance(st, dict):
            st01 = st.get("ST01")
            if isinstance(st01, str) and st01.strip():
                return st01.strip()

        return None
