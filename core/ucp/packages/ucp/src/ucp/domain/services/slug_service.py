"""Pure domain service for generating URL-safe tenant slugs.

This module has zero external dependencies and is fully testable in isolation.
"""

import re

from ucp.core.exceptions import InvalidTenantNameError


def generate_slug(name: str) -> str:
    """Convert a tenant name into a URL-safe, lowercase, hyphen-separated slug.

    Examples:
        >>> generate_slug("Acme Corp")
        'acme-corp'
        >>> generate_slug("  Hello World!  ")
        'hello-world'
        >>> generate_slug("Café & Co.")
        'cafe-co'

    Raises:
        InvalidTenantNameError: If the name contains no alphanumeric characters
            and therefore produces an empty slug.
    """
    slug = name.lower().strip()
    # Normalise accented characters to their ASCII base (best-effort)
    slug = _transliterate(slug)
    # Remove every character that is not lowercase ASCII, digit, space, or hyphen
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    # Collapse whitespace and underscores into single hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Collapse multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    if not slug:
        raise InvalidTenantNameError(
            f"Tenant name {name!r} produces an empty slug. "
            "Please use at least one alphanumeric character."
        )
    return slug


def generate_unique_slug(name: str, existing_slugs: set[str]) -> str:
    """Generate a slug that is guaranteed not to collide with ``existing_slugs``.

    If the base slug is already taken, a numeric suffix is appended:
        acme-corp → acme-corp-2 → acme-corp-3 → …

    Args:
        name: Human-readable tenant name.
        existing_slugs: Set of slugs already present in the database.

    Returns:
        A unique, URL-safe slug string.
    """
    base = generate_slug(name)
    if base not in existing_slugs:
        return base

    counter = 2
    while True:
        candidate = f"{base}-{counter}"
        if candidate not in existing_slugs:
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_TRANSLITERATION_MAP: dict[str, str] = {
    "à": "a",
    "á": "a",
    "â": "a",
    "ã": "a",
    "ä": "a",
    "å": "a",
    "æ": "ae",
    "ç": "c",
    "è": "e",
    "é": "e",
    "ê": "e",
    "ë": "e",
    "ì": "i",
    "í": "i",
    "î": "i",
    "ï": "i",
    "ð": "d",
    "ñ": "n",
    "ò": "o",
    "ó": "o",
    "ô": "o",
    "õ": "o",
    "ö": "o",
    "ù": "u",
    "ú": "u",
    "û": "u",
    "ü": "u",
    "ý": "y",
    "þ": "th",
    "ÿ": "y",
}


def _transliterate(text: str) -> str:
    """Best-effort ASCII transliteration of common Latin accented characters."""
    return "".join(_TRANSLITERATION_MAP.get(ch, ch) for ch in text)
