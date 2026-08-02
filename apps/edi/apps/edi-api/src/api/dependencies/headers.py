from fastapi import Header


def get_idempotency_key(
    idempotency_key: str | None = Header(alias="Idempotency-Key", default=None),
) -> str | None:
    """
    Extracts the Idempotency-Key HTTP header for state-mutating requests.
    """
    return idempotency_key
