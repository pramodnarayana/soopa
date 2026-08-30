import os
from enum import Enum


def generate_id(prefix: Enum | str, entropy_bytes: int = 16) -> str:
    """
    Generate an enterprise-grade Stripe-style prefixed ID.

    Args:
        prefix: A DomainIdPrefix or SystemIdPrefix Enum member (or str fallback)
        entropy_bytes: The number of random bytes to generate (default 16 bytes = 32 hex chars)

    Returns:
        A strictly formatted ID string (e.g. "iam_usr_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p")
    """
    if not prefix:
        raise ValueError("Prefix cannot be empty")

    prefix_val = prefix.value if isinstance(prefix, Enum) else prefix
    return f"{prefix_val}_{os.urandom(entropy_bytes).hex()}"


def generate_random_hex(entropy_bytes: int = 16) -> str:
    """
    Generate a random hex string. Useful for test suffixes or pure randomness.
    """
    return os.urandom(entropy_bytes).hex()
