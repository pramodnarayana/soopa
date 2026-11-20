"""Connection and connector specification enumerations."""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    """Lifecycle status of an integration connection to an external application."""

    ACTIVE = "ACTIVE"
    PENDING_AUTH = "PENDING_AUTH"
    ERROR = "ERROR"
    DEACTIVATED = "DEACTIVATED"


class AuthType(StrEnum):
    """Supported authentication strategies for external application connections."""

    NO_AUTH = "NO_AUTH"
    BASIC_AUTH = "BASIC_AUTH"
    BEARER_TOKEN = "BEARER_TOKEN"  # noqa: S105 - Enum key for authentication strategy, not a secret
    API_KEY = "API_KEY"
    OAUTH2 = "OAUTH2"
    OAUTH2_CLIENT_CREDENTIALS = "OAUTH2_CLIENT_CREDENTIALS"
    MTLS = "MTLS"
    CUSTOM = "CUSTOM"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"
    SASL_SSL = "SASL_SSL"

    @property
    def requires_interactive_authorization(self) -> bool:
        """Indicates whether this auth type requires a 3-legged browser redirect dance (OAuth2).

        Direct credential protocols (Kafka SASL, SFTP, RabbitMQ, API Keys, Basic Auth,
        or unauthenticated PLAINTEXT) do not require out-of-band user consent.
        """
        return self == AuthType.OAUTH2


class ApiKeyPlacement(StrEnum):
    """Transmission placement for API key credentials."""

    HEADER = "HEADER"
    QUERY_PARAM = "QUERY_PARAM"


class ConnectorPropertyKey(StrEnum):
    """Canonical property keys for dynamic connector configuration specifications."""

    BASE_URL = "base_url"
    AUTH_TYPE = "auth_type"
    CHECK_PATH = "check_path"
    TOKEN = "token"  # noqa: S105 - Enum key for property schema definition, not a secret
    PARAM_NAME = "param_name"
    PLACEMENT = "placement"
    USERNAME = "username"
    PASSWORD = "password"  # noqa: S105 - Enum key for property schema definition, not a secret
    TOKEN_URL = "token_url"  # noqa: S105 - Enum key for property schema definition, not a secret
    CLIENT_ID = "client_id"
    CLIENT_SECRET = "client_secret"  # noqa: S105 - Enum key for property schema definition, not a secret
    SCOPES = "scopes"
    TIMEOUT_SECONDS = "timeout_seconds"
    BOOTSTRAP_SERVERS = "bootstrap_servers"
    SECURITY_PROTOCOL = "security_protocol"
    SASL_MECHANISM = "sasl_mechanism"
    DEFAULT_TOPIC = "default_topic"
    PARTITION_KEY_FIELD = "partition_key_field"
    ENDPOINT_SLUG = "endpoint_slug"
    VERIFICATION_STRATEGY = "verification_strategy"
    SECRET_TOKEN = "secret_token"  # noqa: S105 - Enum key for configuration property name, not a secret
    WEBHOOK_MODALITY = "webhook_modality"


class WebhookModality(StrEnum):
    """Execution modality of a webhook connection endpoint."""

    DYNAMIC = "DYNAMIC"
    COMMAND = "COMMAND"
    DATA = "DATA"


class PropertyType(StrEnum):
    """Dynamic UI input types for self-service connector configuration schemas."""

    SHORT_TEXT = "shortText"
    SECRET_TEXT = "secretText"  # noqa: S105 - UI schema property type identifier, not a password credential
    DROPDOWN = "dropdown"
    OAUTH2 = "oauth2"
    NUMBER = "number"
    BOOLEAN = "boolean"


class PaginationType(StrEnum):
    """Declarative pagination strategies supported by declarative HTTP streams."""

    NONE = "none"
    OFFSET_LIMIT = "offset_limit"
    PAGE_NUMBER = "page_number"
    CURSOR = "cursor"
    LINK_HEADER = "link_header"


class EngineConnectorId(StrEnum):
    """Built-in protocol-level engine connector application identifiers."""

    HTTP = "http"
    SFTP = "sftp"
    KAFKA = "kafka"
    REDPANDA = "redpanda"
    WEBHOOK = "webhook"


class CatalogCategory(StrEnum):
    """Standard domain-agnostic application categories for the connector catalog."""

    API = "API"
    CRM = "CRM"
    BILLING = "BILLING"
    STORAGE = "STORAGE"
    SANDBOX = "SANDBOX"
    ITSM = "ITSM"
    MESSAGING = "MESSAGING"


class ConnectorRole(StrEnum):
    """Architectural role of the connector in the integration topology."""

    OUTBOUND_CLIENT = "OUTBOUND_CLIENT"
    INBOUND_GATEWAY = "INBOUND_GATEWAY"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class ConnectorArchitectureType(StrEnum):
    """Runtime architecture classifications for catalog connectors."""

    DECLARATIVE_HTTP = "DECLARATIVE_HTTP"
    GENERIC_HTTP = "GENERIC_HTTP"
    NATIVE_PROTOCOL = "NATIVE_PROTOCOL"
    NATIVE_SIMULATOR = "NATIVE_SIMULATOR"
    CUSTOM_PYTHON = "CUSTOM_PYTHON"
