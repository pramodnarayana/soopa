"""Strongly-typed domain exceptions and error objects for webhook ingress."""

from __future__ import annotations

from dataclasses import dataclass

from ip.engine.domain.exceptions import IpError, IpErrorCode


@dataclass(frozen=True)
class WebhookEndpointNotFoundError(IpError):
    """Raised/returned when a requested webhook endpoint cannot be resolved."""

    code: IpErrorCode = IpErrorCode.WEBHOOK_ENDPOINT_NOT_FOUND
    message: str = "Webhook endpoint not found."

    @classmethod
    def for_slug(cls, tenant_id: str, endpoint_slug: str) -> WebhookEndpointNotFoundError:
        return cls(
            message=f"Webhook endpoint '{endpoint_slug}' for tenant '{tenant_id}' was not found.",
            details={"tenant_id": tenant_id, "endpoint_slug": endpoint_slug},
        )


@dataclass(frozen=True)
class WebhookEndpointDeactivatedError(IpError):
    """Raised/returned when an inbound push targets an inactive endpoint."""

    code: IpErrorCode = IpErrorCode.WEBHOOK_ENDPOINT_DEACTIVATED
    message: str = "Webhook endpoint is deactivated."

    @classmethod
    def for_slug(cls, tenant_id: str, endpoint_slug: str) -> WebhookEndpointDeactivatedError:
        return cls(
            message=f"Webhook endpoint '{endpoint_slug}' is currently deactivated.",
            details={"tenant_id": tenant_id, "endpoint_slug": endpoint_slug},
        )


@dataclass(frozen=True)
class UnmappedEventRouteError(IpError):
    """Raised/returned when an incoming event discriminator cannot be matched to any active route."""

    code: IpErrorCode = IpErrorCode.UNMAPPED_EVENT_ROUTE
    message: str = "No matching route found for event discriminator."

    @classmethod
    def for_event(
        cls, endpoint_slug: str, event_discriminator: str | None
    ) -> UnmappedEventRouteError:
        return cls(
            message=f"Event discriminator '{event_discriminator}' has no active route on endpoint '{endpoint_slug}'.",
            details={"endpoint_slug": endpoint_slug, "event_discriminator": event_discriminator},
        )


@dataclass(frozen=True)
class WebhookVerificationFailedError(IpError):
    """Raised/returned when an inbound webhook fails perimeter cryptographic or token verification."""

    code: IpErrorCode = IpErrorCode.WEBHOOK_VERIFICATION_FAILED
    message: str = "Webhook authentication verification failed."


@dataclass(frozen=True)
class DuplicateWebhookEndpointSlugError(IpError):
    """Raised/returned when attempting to create an endpoint slug that already exists for the tenant."""

    code: IpErrorCode = IpErrorCode.DUPLICATE_WEBHOOK_ENDPOINT_SLUG
    message: str = "Webhook endpoint slug already exists for tenant."
