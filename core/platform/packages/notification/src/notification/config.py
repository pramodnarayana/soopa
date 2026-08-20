"""
Notification Engine Settings.

A frozen, typed configuration value object for the Notification Engine bounded context.
Populated by the DI container from environment/config at startup — never hardcoded in
application or infrastructure code.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationEngineSettings:
    """
    Immutable settings for the Notification Engine.

    All business-rule constants live here so they are:
    - Discoverable (one place to look)
    - Testable (inject overrides in tests without patching globals)
    - Configurable (wire from environment via the DI container)
    """

    max_template_size_chars: int = 10_000
    """Maximum allowed characters for a Jinja2 template body or subject."""

    max_payload_size_chars: int = 50_000
    """Maximum allowed characters for the serialized JSON mock/live payload."""

    render_timeout_seconds: float = 2.0
    """Per-render timeout (seconds) enforced in the thread-pool executor."""
