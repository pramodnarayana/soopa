"""Domain value objects defining the Generic HTTP Connector per-connection contract."""

from __future__ import annotations

from dataclasses import dataclass, field

from seedwork.domain.types import JsonValue

from ip.engine.domain.enums import AuthType, HttpWriteOperation, PaginationType
from ip.engine.domain.models.stream_definition import StreamDefinition

BLOCKED_HEADERS = frozenset(
    {
        "host",
        "authorization",
        "proxy-authorization",
        "connection",
        "upgrade",
        "te",
        "trailer",
        "transfer-encoding",
    }
)


@dataclass(frozen=True)
class HttpRequestSpec:
    """HTTP request parameters for extracting or probing a stream."""

    path: str
    method: str = "GET"
    query_params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body_template: str | None = None
    pagination: PaginationType = PaginationType.NONE
    pagination_params: dict[str, JsonValue] = field(default_factory=dict)
    incremental_param: str | None = None

    def __post_init__(self) -> None:
        for header in self.headers:
            if header.lower() in BLOCKED_HEADERS:
                raise ValueError(
                    f"Header '{header}' is blocked from declarative request specs for security."
                )


@dataclass(frozen=True)
class HttpWriteAction:
    """Outbound write action definition (method + URL path template)."""

    method: str
    path_template: str


@dataclass(frozen=True)
class HttpWriteSpec:
    """Optional L5 outbound write actions per operation."""

    actions: dict[HttpWriteOperation, HttpWriteAction] = field(default_factory=dict)


@dataclass(frozen=True)
class HttpStreamDefinition:
    """Composed stream definition representing request execution and replication semantics."""

    request: HttpRequestSpec
    replication: StreamDefinition
    write: HttpWriteSpec | None = None
    normalizer_id: str | None = None
    fetch_one: HttpRequestSpec | None = None


@dataclass(frozen=True)
class HttpSourceSpec:
    """Typed, immutable per-connection contract for GenericHttpConnector."""

    base_url: str
    auth_type: AuthType
    default_headers: dict[str, str] = field(default_factory=dict)
    check_request: HttpRequestSpec | None = None
    streams: tuple[HttpStreamDefinition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        clean_url = self.base_url.strip().lower()
        if not clean_url.startswith(("https://", "http://")):
            raise ValueError(
                f"Invalid base_url: '{self.base_url}'. Must start with https:// or http://."
            )
        for header in self.default_headers:
            if header.lower() in BLOCKED_HEADERS:
                raise ValueError(f"Header '{header}' is blocked from default_headers for security.")

    def get_stream(self, stream_name: str) -> HttpStreamDefinition | None:
        for stream in self.streams:
            if stream.replication.stream == stream_name:
                return stream
        return None
