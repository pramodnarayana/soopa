"""Configuration models for the Pub/Sub platform capability package."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings

from pubsub.domain.exceptions import InvalidBrokerTransportError
from pubsub.provider import PubSubProvider
from pubsub.registry import BrokerTransportRegistry

_AWS_ENDPOINT_FAMILY = "aws"


class PlatformPubSubSettings(CleanBaseSettings):
    """Centralized, Open-Closed Pub/Sub transport policy configuration.

    Mirrors ``PlatformIdentitySettings`` in ``identity.config``: validates
    ``PUBSUB_TRANSPORT`` and configured queue/topic URIs dynamically against
    the active ``BrokerTransportRegistry`` without hardcoding any broker list.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    transport: str | None = Field(
        validation_alias="PUBSUB_TRANSPORT",
        default=None,
        description=(
            "Active Pub/Sub transport policy name registered in BrokerTransportRegistry. "
            "When set, every configured queue and topic URI must match this transport."
        ),
    )

    @field_validator("transport", mode="before")
    @classmethod
    def _normalize_transport(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError(f"PUBSUB_TRANSPORT must be a string, got {type(value).__name__}.")
        stripped = value.strip().lower()
        return stripped or None

    def validate_uris(
        self,
        uris: Mapping[str, str | None],
        *,
        registry: BrokerTransportRegistry | None = None,
    ) -> None:
        """Fail fast at startup when ``PUBSUB_TRANSPORT`` or any URI violates the registry."""
        active_registry = registry or PubSubProvider.default_registry()
        try:
            normalized = active_registry.normalize_transport(self.transport)
        except InvalidBrokerTransportError as exc:
            raise ValueError(exc.reason) from exc

        if normalized is None:
            return

        violations: list[str] = []
        for field_name, raw_uri in uris.items():
            uri = (raw_uri or "").strip()
            if not uri:
                continue
            violation = active_registry.check_policy(uri, transport=normalized)
            if violation is not None:
                violations.append(f"{field_name}='{uri}'")

        if violations:
            remedy = active_registry.remedy_for_transport(normalized)
            joined = ", ".join(violations)
            raise ValueError(
                f"PUBSUB_TRANSPORT='{normalized}' forbids configured URI(s): {joined}. {remedy}"
            )

    def effective_endpoint_url(
        self,
        endpoint_url: str | None,
        *,
        family: str,
        registry: BrokerTransportRegistry | None = None,
    ) -> str | None:
        """Suppresses custom endpoint overrides when the active transport does not match ``family``."""
        active_registry = registry or PubSubProvider.default_registry()
        if not active_registry.supports_endpoint_family(self.transport, family=family):
            return None
        cleaned = (endpoint_url or "").strip()
        return cleaned or None

    def effective_aws_endpoint_url(
        self,
        endpoint_url: str | None,
        *,
        registry: BrokerTransportRegistry | None = None,
    ) -> str | None:
        """Convenience wrapper suppressing AWS endpoint overrides for non-AWS transports."""
        return self.effective_endpoint_url(
            endpoint_url,
            family=_AWS_ENDPOINT_FAMILY,
            registry=registry,
        )
