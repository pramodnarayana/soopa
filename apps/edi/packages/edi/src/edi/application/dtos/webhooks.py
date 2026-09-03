from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookDTO:
    """
    Maps to the Webhook table.
    Typed return value of get_webhook() — replaces raw dict[str, Any].
    """

    id: str
    url: str
    name: str
    active: bool
    auth_header_vault_ref: str | None = None
