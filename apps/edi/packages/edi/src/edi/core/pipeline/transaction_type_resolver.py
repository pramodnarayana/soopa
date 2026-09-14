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
    def _extract_from_dict(payload_dict: Mapping[str, object]) -> str | None:
        """Extract from a single payload dict using the ordered cascade."""

        # Pattern 1: flat field
        val = payload_dict.get("transaction_type")
        if isinstance(val, str) and val.strip():
            return val.strip()

        # Pattern 2: heading-based EDI JSON structure
        heading = payload_dict.get("heading")
        if isinstance(heading, dict):
            for key in heading:
                if isinstance(key, str) and key.startswith("transaction_set_header_ST"):
                    inner = heading[key]
                    if isinstance(inner, dict):
                        inner_val = inner.get("transaction_set_identifier_code") or inner.get(
                            "transaction_set_identifier_code_01"
                        )
                        if isinstance(inner_val, str) and inner_val.strip():
                            return inner_val.strip()
                    break  # Only one ST header per transaction

        # Pattern 3: raw ST segment shorthand
        st = payload_dict.get("ST")
        if isinstance(st, dict):
            st01 = st.get("ST01")
            if isinstance(st01, str) and st01.strip():
                return st01.strip()

        return None
