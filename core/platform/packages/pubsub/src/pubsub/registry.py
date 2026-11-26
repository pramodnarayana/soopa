"""Open-Closed Broker Transport Registry for Pub/Sub adapters and transport policies.

New message brokers (e.g., NATS, Redis Streams, Azure Service Bus, GCP Pub/Sub)
plug into the platform by registering a ``BrokerTransportSpec`` without modifying
``seedwork``, ``PlatformPubSubSettings``, or ``PubSubProvider``'s routing/policy logic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from outbox.ports.shard_outbox_drain_port import ShardOutboxDrainPort
from sqlalchemy.ext.asyncio import AsyncSession

from pubsub.domain.dtos import TopicSubscriptionSpec
from pubsub.domain.enums import PayloadDispatchMode
from pubsub.domain.exceptions import (
    BrokerTransportMismatchError,
    InvalidBrokerTransportError,
    UnsupportedBrokerSchemeError,
)
from pubsub.ports.consumer_error_handler_port import ConsumerErrorHandlerPort
from pubsub.ports.consumer_manager_port import ConsumerManagerPort, MessageHandler
from pubsub.ports.database_queue_port import DatabaseQueuePort
from pubsub.ports.message_publisher_port import MessagePublisherPort

logger = structlog.get_logger(__name__)

SessionScopeFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class TransportPolicyViolation:
    """First-class structured violation returned when a URI conflicts with a transport policy."""

    transport: str
    uri: str
    matched_transport: str | None
    remedy: str


@dataclass(frozen=True)
class ConsumerBuildRequest:
    """Typed parameter bundle passed to a registered broker's consumer factory."""

    source_uri: str
    handler: MessageHandler
    group_id: str
    region_name: str
    endpoint_url: str | None
    bootstrap_servers: str | None
    use_in_memory: bool
    error_handler: ConsumerErrorHandlerPort | None
    poll_sleep_seconds: float
    error_sleep_seconds: float
    shard_drain_repo: ShardOutboxDrainPort | None
    dlq_publisher: OutboxPublisherPort | None
    global_outbox_repo: OutboxRepositoryPort | None
    database_queue: DatabaseQueuePort | None
    session_factory: SessionScopeFactory | None
    database_url: str | None
    subscribe_topics: Sequence[str | TopicSubscriptionSpec] | None
    dispatch_mode: PayloadDispatchMode
    batch_size: int
    lock_lease_ms: int


@dataclass(frozen=True)
class OutboxPublisherBuildRequest:
    """Typed parameter bundle passed to a registered broker's outbox publisher factory."""

    destination_uri: str
    region_name: str
    endpoint_url: str | None
    bootstrap_servers: str | None
    use_in_memory: bool
    max_concurrent_batches: int
    database_queue: DatabaseQueuePort | None
    session_factory: SessionScopeFactory | None
    database_url: str | None


@dataclass(frozen=True)
class PublisherBuildRequest:
    """Typed parameter bundle passed to a registered broker's direct publisher factory."""

    destination_uri: str
    region_name: str
    endpoint_url: str | None
    bootstrap_servers: str | None
    use_in_memory: bool
    database_queue: DatabaseQueuePort | None
    session_factory: SessionScopeFactory | None
    database_url: str | None


ConsumerFactory = Callable[[ConsumerBuildRequest], ConsumerManagerPort]
OutboxPublisherFactory = Callable[[OutboxPublisherBuildRequest], OutboxPublisherPort]
PublisherFactory = Callable[[PublisherBuildRequest], MessagePublisherPort]


@dataclass(frozen=True)
class BrokerTransportSpec:
    """Self-describing plugin contract for a concrete Pub/Sub broker transport."""

    name: str
    uri_prefixes: tuple[str, ...]
    remedy: str = ""
    endpoint_family: str | None = None
    build_consumer: ConsumerFactory | None = None
    build_outbox_publisher: OutboxPublisherFactory | None = None
    build_publisher: PublisherFactory | None = None

    def normalized_name(self) -> str:
        return self.name.strip().lower()

    def normalized_endpoint_family(self) -> str | None:
        if self.endpoint_family is None:
            return None
        cleaned = self.endpoint_family.strip().lower()
        return cleaned or None

    def normalized_prefixes(self) -> tuple[str, ...]:
        return tuple(prefix.strip().lower() for prefix in self.uri_prefixes if prefix.strip())

    def matching_prefix_length(self, uri: str) -> int:
        normalized_uri = uri.strip().lower()
        longest = 0
        for prefix in self.normalized_prefixes():
            if normalized_uri.startswith(prefix) and len(prefix) > longest:
                longest = len(prefix)
        return longest

    def effective_remedy(self) -> str:
        if self.remedy:
            return self.remedy
        prefixes = ", ".join(self.normalized_prefixes())
        return f"Update broker URIs to match transport '{self.normalized_name()}' ({prefixes})."


@dataclass(frozen=True)
class BrokerPolicyGroup:
    """Composite transport policy grouping multiple registered broker specs."""

    name: str
    member_names: frozenset[str]
    remedy: str = ""
    endpoint_family: str | None = None

    def normalized_name(self) -> str:
        return self.name.strip().lower()

    def normalized_endpoint_family(self) -> str | None:
        if self.endpoint_family is None:
            return None
        cleaned = self.endpoint_family.strip().lower()
        return cleaned or None

    def normalized_members(self) -> frozenset[str]:
        return frozenset(member.strip().lower() for member in self.member_names if member.strip())


def extract_uri_scheme_label(uri: str) -> str:
    """Extracts a safe human-readable scheme label from an unrecognized broker URI."""
    stripped = uri.strip()
    if "://" in stripped:
        return stripped.split("://", 1)[0]
    return "unknown"


class BrokerTransportRegistry:
    """Open-Closed registry resolving broker specs and enforcing transport policies."""

    def __init__(self) -> None:
        self._specs: dict[str, BrokerTransportSpec] = {}
        self._groups: dict[str, BrokerPolicyGroup] = {}
        self._frozen: bool = False

    @property
    def is_frozen(self) -> bool:
        """Returns True once the registry has been locked against in-place mutation."""
        return self._frozen

    def freeze(self) -> BrokerTransportRegistry:
        """Locks this registry against further mutations; callers must ``.copy()`` to extend."""
        self._frozen = True
        return self

    def _assert_mutable(self) -> None:
        if self._frozen:
            raise RuntimeError(
                "Cannot mutate a frozen BrokerTransportRegistry; call .copy() to create an extensible copy."
            )

    def register(self, spec: BrokerTransportSpec) -> None:
        """Registers a broker plugin specification (open for extension)."""
        self._assert_mutable()
        key = spec.normalized_name()
        if not key:
            raise ValueError("BrokerTransportSpec.name must be non-empty.")
        if not spec.normalized_prefixes():
            raise ValueError(f"BrokerTransportSpec '{key}' must declare at least one URI prefix.")
        self._specs[key] = spec

    def register_policy_group(self, group: BrokerPolicyGroup) -> None:
        """Registers a named policy group spanning one or more registered transport specs."""
        self._assert_mutable()
        key = group.normalized_name()
        if not key:
            raise ValueError("BrokerPolicyGroup.name must be non-empty.")
        members = group.normalized_members()
        if not members:
            raise ValueError(f"BrokerPolicyGroup '{key}' must declare at least one member.")
        unknown = sorted(members - set(self._specs))
        if unknown:
            raise ValueError(
                f"BrokerPolicyGroup '{key}' references unregistered transport(s): {', '.join(unknown)}."
            )
        self._groups[key] = group

    def known_transports(self) -> tuple[str, ...]:
        """Returns all valid PUBSUB_TRANSPORT policy names (registered specs + policy groups)."""
        return tuple(sorted({*self._specs.keys(), *self._groups.keys()}))

    def supported_prefixes(self) -> tuple[str, ...]:
        """Returns all registered URI prefixes in deterministic order."""
        prefixes: list[str] = []
        for spec in self._specs.values():
            for prefix in spec.normalized_prefixes():
                if prefix not in prefixes:
                    prefixes.append(prefix)
        return tuple(prefixes)

    def get_spec(self, name: str) -> BrokerTransportSpec | None:
        """Looks up a registered spec by normalized transport name."""
        return self._specs.get(name.strip().lower())

    def normalize_transport(self, raw: str | None) -> str | None:
        """Validates a transport policy name against registered specs and policy groups."""
        if raw is None:
            return None
        normalized = raw.strip().lower()
        if not normalized:
            return None
        if normalized in self._specs or normalized in self._groups:
            return normalized
        valid = ", ".join(self.known_transports())
        reason = f"Unsupported PUBSUB_TRANSPORT='{raw}'. Registered transports: {valid}."
        logger.error(
            "pubsub_invalid_transport_policy",
            transport=raw,
            registered_transports=list(self.known_transports()),
        )
        raise InvalidBrokerTransportError(transport=raw, reason=reason)

    def resolve_uri(self, uri: str) -> BrokerTransportSpec | None:
        """Resolves a URI strictly by longest matching registered prefix (fail closed)."""
        best_spec: BrokerTransportSpec | None = None
        best_length = 0
        for spec in self._specs.values():
            match_len = spec.matching_prefix_length(uri)
            if match_len > best_length:
                best_length = match_len
                best_spec = spec
        return best_spec

    def resolve_uri_or_raise(self, uri: str) -> BrokerTransportSpec:
        """Resolves a URI or raises ``UnsupportedBrokerSchemeError`` with registered prefixes."""
        spec = self.resolve_uri(uri)
        if spec is None:
            raise UnsupportedBrokerSchemeError(
                extract_uri_scheme_label(uri),
                supported_prefixes=self.supported_prefixes(),
            )
        return spec

    def allowed_spec_names(self, transport: str) -> frozenset[str]:
        """Returns the set of registered broker spec names permitted by ``transport``."""
        normalized = self.normalize_transport(transport)
        if normalized is None:
            return frozenset(self._specs.keys())
        if normalized in self._groups:
            return self._groups[normalized].normalized_members()
        return frozenset({normalized})

    def remedy_for_transport(self, transport: str) -> str:
        """Returns the operator remediation message registered for ``transport``."""
        normalized = self.normalize_transport(transport)
        if normalized is None:
            return ""
        if normalized in self._groups:
            group = self._groups[normalized]
            if group.remedy:
                return group.remedy
            members = ", ".join(sorted(group.normalized_members()))
            return f"Update broker URIs to match transport group '{normalized}' ({members})."
        return self._specs[normalized].effective_remedy()

    def supports_endpoint_family(self, transport: str | None, *, family: str) -> bool:
        """Returns True when ``transport`` permits custom endpoint overrides for ``family``."""
        normalized = self.normalize_transport(transport)
        if normalized is None:
            return True
        target_family = family.strip().lower()
        if normalized in self._groups:
            return self._groups[normalized].normalized_endpoint_family() == target_family
        return self._specs[normalized].normalized_endpoint_family() == target_family

    def check_policy(
        self,
        uri: str,
        *,
        transport: str | None,
        matched_spec: BrokerTransportSpec | None = None,
    ) -> TransportPolicyViolation | None:
        """Pure, non-throwing policy check returning a structured violation or ``None``."""
        normalized = self.normalize_transport(transport)
        if normalized is None:
            return None
        resolved = matched_spec if matched_spec is not None else self.resolve_uri(uri)
        allowed = self.allowed_spec_names(normalized)
        if resolved is None or resolved.normalized_name() not in allowed:
            return TransportPolicyViolation(
                transport=normalized,
                uri=uri,
                matched_transport=resolved.normalized_name() if resolved is not None else None,
                remedy=self.remedy_for_transport(normalized),
            )
        return None

    def enforce_policy(
        self,
        uri: str,
        *,
        transport: str | None,
        matched_spec: BrokerTransportSpec | None = None,
    ) -> None:
        """Enforces that ``uri`` (or ``matched_spec``) satisfies the injected transport policy."""
        violation = self.check_policy(uri, transport=transport, matched_spec=matched_spec)
        if violation is not None:
            logger.error(
                "pubsub_transport_uri_mismatch",
                transport=violation.transport,
                uri=violation.uri,
                matched_transport=violation.matched_transport,
                remedy=violation.remedy,
            )
            raise BrokerTransportMismatchError(
                transport=violation.transport,
                uri=violation.uri,
                remedy=violation.remedy,
            )

    def copy(self) -> BrokerTransportRegistry:
        """Creates an isolated, mutable shallow copy of this registry for extension or testing."""
        cloned = BrokerTransportRegistry()
        cloned._specs = dict(self._specs)
        cloned._groups = dict(self._groups)
        return cloned
