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
