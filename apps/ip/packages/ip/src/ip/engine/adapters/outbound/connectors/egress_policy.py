"""Egress policy adapters enforcing SSRF guards, private IP blocking, and scheme validation via platform shttp."""

from __future__ import annotations

from urllib.parse import urlsplit

from ip.engine.domain.exceptions import EndpointSecurityViolationError, Result
from ip.engine.ports.outbound.egress_policy_port import EgressPolicyPort
from shttp.exceptions import SsrfSecurityError
from shttp.security.ssrf import ssrf_safe_context

_LOCAL_TEST_HOSTS = ("localhost", "127.0.0.1", "::1", "testserver")


class PublicInternetEgressPolicy(EgressPolicyPort):
    """Default egress adapter blocking loopback, private, link-local, and cloud metadata targets via platform shttp."""

    def __init__(self, *, allow_private_ips: bool = False) -> None:
        self._allow_private_ips = allow_private_ips

    def validate_url(self, url: str) -> Result[None, EndpointSecurityViolationError]:
        """Validates target URL against scheme, hostname, and SSRF security policies using centralized platform shttp."""
        try:
            parsed = urlsplit(url)
            if (
                not self._allow_private_ips
                and parsed.scheme.lower() == "http"
                and parsed.hostname not in _LOCAL_TEST_HOSTS
            ):
                return Result.fail(
                    EndpointSecurityViolationError(
                        endpoint=url,
                        message=f"Insecure scheme 'http' is not permitted for public endpoint '{url}'. HTTPS is required.",
                        details={"scheme": parsed.scheme, "host": parsed.hostname},
                    )
                )

            with ssrf_safe_context(url, allow_private_ips=self._allow_private_ips):
                pass
            return Result.ok(None)
        except SsrfSecurityError as exc:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=url,
                    message=str(exc),
                    details={"reason": exc.reason.value if exc.reason else "SSRF_VIOLATION"},
                )
            )
        except (ValueError, OSError) as exc:
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=url,
                    message=f"URL validation failed: {exc}",
                )
            )
