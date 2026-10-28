"""First-class domain and operational error value objects for the Integration Platform.

Strictly adheres to the First-Class Error Handling standard:
- Known domain and operational errors are represented as strongly-typed, immutable
  value objects (`IpError` subclasses) and returned via `Result[T, IpError]` or
  structured boundary DTOs.
- Exceptions are NEVER raised for known domain or operational outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.exceptions import Result
from seedwork.domain.types import JsonDict

from ip.engine.domain.enums import FailureDisposition


class IpErrorCode(StrEnum):
    """Strongly-typed error codes for all known Integration Platform outcomes."""

    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_DEACTIVATED = "CONNECTION_DEACTIVATED"
    DUPLICATE_FINGERPRINT = "DUPLICATE_FINGERPRINT"
    INVALID_CONNECTION_STATE = "INVALID_CONNECTION_STATE"
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_ENDPOINT = "INVALID_ENDPOINT"
    ENDPOINT_SECURITY_VIOLATION = "ENDPOINT_SECURITY_VIOLATION"
    CONNECTOR_NOT_FOUND = "CONNECTOR_NOT_FOUND"
    STREAM_NOT_FOUND = "STREAM_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    HTTP_ERROR = "HTTP_ERROR"
    REMOTE_ERROR = "REMOTE_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    SFTP_CONNECTION_FAILED = "SFTP_CONNECTION_FAILED"
    CATALOG_DISCOVERY_FAILED = "CATALOG_DISCOVERY_FAILED"
    MANIFEST_PARSE_ERROR = "MANIFEST_PARSE_ERROR"
    UNSUPPORTED_WRITE_OPERATION = "UNSUPPORTED_WRITE_OPERATION"
    WRITE_ACTION_NOT_CONFIGURED = "WRITE_ACTION_NOT_CONFIGURED"
    PAYLOAD_NOT_FOUND = "PAYLOAD_NOT_FOUND"
    TENANT_SHARD_NOT_FOUND = "TENANT_SHARD_NOT_FOUND"
    ACTIVE_SYNC_RUN_EXISTS = "ACTIVE_SYNC_RUN_EXISTS"
    SYNC_RUN_NOT_FOUND = "SYNC_RUN_NOT_FOUND"
    INBOUND_VERIFICATION_FAILED = "INBOUND_VERIFICATION_FAILED"
    INBOUND_PAYLOAD_DECODE_FAILED = "INBOUND_PAYLOAD_DECODE_FAILED"
    DUPLICATE_EXTERNAL_EVENT = "DUPLICATE_EXTERNAL_EVENT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    TRANSFORMER_NOT_FOUND = "TRANSFORMER_NOT_FOUND"
    TRANSFORMATION_NOT_FOUND = "TRANSFORMATION_NOT_FOUND"
    REPLICA_RECORD_NOT_FOUND = "REPLICA_RECORD_NOT_FOUND"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    STITCH_DEFINITION_NOT_FOUND = "STITCH_DEFINITION_NOT_FOUND"
    STITCH_RUN_NOT_FOUND = "STITCH_RUN_NOT_FOUND"
    TRACE_NOT_FOUND = "TRACE_NOT_FOUND"
    REPLAY_STAGE_NOT_AVAILABLE = "REPLAY_STAGE_NOT_AVAILABLE"
    INVALID_REPLAY_PAYLOAD = "INVALID_REPLAY_PAYLOAD"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    EXTERNAL_API_ERROR = "EXTERNAL_API_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, kw_only=True)
class IpError:
    """Base value object for all known Integration Platform errors (NOT an Exception)."""

    code: IpErrorCode
    message: str
    disposition: FailureDisposition = FailureDisposition.FAIL
    remediation: str | None = None
    http_status: int = 400
    details: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ConnectionNotFoundError(IpError):
    """Returned when a referenced connection ID does not exist or belongs to another tenant."""

    connection_id: str = ""
    code: IpErrorCode = IpErrorCode.CONNECTION_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify the connection_id exists and belongs to the active tenant."

    @classmethod
    def for_id(cls, connection_id: str) -> ConnectionNotFoundError:
        return cls(
            connection_id=connection_id,
            message=f"Connection '{connection_id}' was not found.",
            details={"connection_id": connection_id},
        )


@dataclass(frozen=True, kw_only=True)
class ConnectionDeactivatedError(IpError):
    """Returned when an operation is attempted against a soft-deactivated connection."""

    connection_id: str = ""
    code: IpErrorCode = IpErrorCode.CONNECTION_DEACTIVATED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409
    remediation: str | None = "Relink the deactivated connection before resuming operations."

    @classmethod
    def for_id(cls, connection_id: str) -> ConnectionDeactivatedError:
        return cls(
            connection_id=connection_id,
            message=f"Connection '{connection_id}' is deactivated and cannot accept ingress.",
            details={"connection_id": connection_id},
        )


@dataclass(frozen=True, kw_only=True)
class DuplicateConnectionFingerprintError(IpError):
    """Returned when an active connection already exists with the same external fingerprint."""

    tenant_id: str = ""
    app_id: str = ""
    fingerprint: str = ""
    code: IpErrorCode = IpErrorCode.DUPLICATE_FINGERPRINT
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409
    remediation: str | None = (
        "Reuse the existing connection for this endpoint or deactivate it before creating a new one."
    )

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        app_id: str,
        fingerprint: str,
    ) -> DuplicateConnectionFingerprintError:
        return cls(
            tenant_id=tenant_id,
            app_id=app_id,
            fingerprint=fingerprint,
            message=(f"A connection for {app_id} already exists with fingerprint {fingerprint}."),
            details={
                "tenant_id": tenant_id,
                "app_id": app_id,
                "fingerprint": fingerprint,
            },
        )


@dataclass(frozen=True, kw_only=True)
class InvalidConnectionStateError(IpError):
    """Returned when a lifecycle transition violates the Connection state machine."""

    connection_id: str = ""
    current_status: str = ""
    attempted_action: str = ""
    code: IpErrorCode = IpErrorCode.INVALID_CONNECTION_STATE
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409
    remediation: str | None = (
        "Ensure the connection is in a valid lifecycle state for the requested transition."
    )


@dataclass(frozen=True, kw_only=True)
class InvalidConnectionConfigError(IpError):
    """Returned when connection or catalog parameters fail domain/configuration validation."""

    field_name: str | None = None
    code: IpErrorCode = IpErrorCode.INVALID_CONFIG
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = "Provide all required non-empty configuration parameters."


@dataclass(frozen=True, kw_only=True)
class InvalidCredentialsError(IpError):
    """Returned when required authentication credentials or tokens are missing or malformed."""

    field_name: str | None = None
    code: IpErrorCode = IpErrorCode.INVALID_CREDENTIALS
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 422
    remediation: str | None = (
        "Supply all required authentication credentials (e.g. api_key, token)."
    )


@dataclass(frozen=True, kw_only=True)
class InvalidEndpointError(IpError):
    """Returned when an endpoint URL is missing, malformed, or uses an invalid scheme."""

    endpoint: str = ""
    code: IpErrorCode = IpErrorCode.INVALID_ENDPOINT
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = "Configure a valid HTTPS endpoint URL with a hostname."


@dataclass(frozen=True, kw_only=True)
class EndpointSecurityViolationError(IpError):
    """Returned when an endpoint URL violates SSRF, origin pinning, or restricted host policies."""

    endpoint: str = ""
    code: IpErrorCode = IpErrorCode.ENDPOINT_SECURITY_VIOLATION
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = (
        "Ensure the endpoint uses HTTPS, targets a public routable host, and matches the base URL origin."
    )


@dataclass(frozen=True, kw_only=True)
class ConnectorNotFoundError(IpError):
    """Returned when an unknown application/connector ID is requested from the catalog."""

    app_id: str = ""
    code: IpErrorCode = IpErrorCode.CONNECTOR_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify the app_id against /api/v1/ip/catalog/apps."

    @classmethod
    def for_app(cls, app_id: str) -> ConnectorNotFoundError:
        return cls(
            app_id=app_id,
            message=f"Connector '{app_id}' not found.",
            details={"app_id": app_id},
        )


@dataclass(frozen=True, kw_only=True)
class StreamNotFoundError(IpError):
    """Returned when a stream is requested that does not exist in the connector's catalog."""

    app_id: str = ""
    stream_name: str = ""
    code: IpErrorCode = IpErrorCode.STREAM_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify the stream name exists in the discovered connection catalog."


@dataclass(frozen=True, kw_only=True)
class AuthenticationFailedError(IpError):
    """Returned when external credential verification fails (e.g. HTTP 401/403)."""

    app_id: str = ""
    status_code: int | None = None
    code: IpErrorCode = IpErrorCode.UNAUTHORIZED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 422
    remediation: str | None = (
        "Verify that your API key, OAuth token, or username/password credentials are valid."
    )


@dataclass(frozen=True, kw_only=True)
class UpstreamHttpError(IpError):
    """Returned when an upstream HTTP endpoint returns a non-success status code."""

    status_code: int = 500
    code: IpErrorCode = IpErrorCode.HTTP_ERROR
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 502
    remediation: str | None = "Check upstream service status and request payload parameters."


@dataclass(frozen=True, kw_only=True)
class UpstreamRemoteError(IpError):
    """Returned when a remote application fails during schema discovery or stream operations."""

    status_code: int = 500
    code: IpErrorCode = IpErrorCode.REMOTE_ERROR
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 502
    remediation: str | None = "Check remote service health and retry the operation."


@dataclass(frozen=True, kw_only=True)
class UpstreamNetworkError(IpError):
    """Returned when a socket, DNS, timeout, or transport failure occurs talking to an upstream host."""

    endpoint: str = ""
    code: IpErrorCode = IpErrorCode.NETWORK_ERROR
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 502
    remediation: str | None = (
        "Verify network connectivity, DNS resolution, and firewall egress rules for the target endpoint."
    )


@dataclass(frozen=True, kw_only=True)
class SftpConnectionError(IpError):
    """Returned when an SFTP connection or file operation fails."""

    host: str = ""
    code: IpErrorCode = IpErrorCode.SFTP_CONNECTION_FAILED
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 502
    remediation: str | None = (
        "Verify the SFTP host, port, SSH credentials, and expected host key fingerprint."
    )


@dataclass(frozen=True, kw_only=True)
class ConnectionCheckError(IpError):
    """Returned when a connection check to an external transport or broker fails."""

    code: IpErrorCode = IpErrorCode.REMOTE_ERROR
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 502
    remediation: str | None = "Verify host, port, credentials, and network firewall policies."


@dataclass(frozen=True, kw_only=True)
class CatalogDiscoveryError(IpError):
    """Returned when schema or stream discovery fails against the external system."""

    connection_id: str = ""
    code: IpErrorCode = IpErrorCode.CATALOG_DISCOVERY_FAILED
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 502
    remediation: str | None = "Verify the connection credentials and upstream schema endpoint."


@dataclass(frozen=True, kw_only=True)
class ManifestParseFailureError(IpError):
    """Returned when a declarative connector manifest fails structural or schema validation."""

    field_name: str | None = None
    code: IpErrorCode = IpErrorCode.MANIFEST_PARSE_ERROR
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = (
        "Ensure the declarative manifest contains valid JSON/YAML and required fields."
    )


@dataclass(frozen=True, kw_only=True)
class UnsupportedWriteOperationError(IpError):
    """Returned when a caller requests an unsupported write operation on a connector stream."""

    operation: str = ""
    stream_name: str = ""
    code: IpErrorCode = IpErrorCode.UNSUPPORTED_WRITE_OPERATION
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = (
        "Use a supported write operation (e.g. CREATE, UPDATE, UPSERT, DELETE)."
    )


@dataclass(frozen=True, kw_only=True)
class WriteActionNotConfiguredError(IpError):
    """Returned when a write operation is requested for a stream without a write_action spec."""

    app_id: str = ""
    stream_name: str = ""
    code: IpErrorCode = IpErrorCode.WRITE_ACTION_NOT_CONFIGURED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = "Configure a write_action for this stream in the connector manifest."


@dataclass(frozen=True, kw_only=True)
class PayloadNotFoundError(IpError):
    """Returned when an offloaded or inline payload cannot be retrieved from tiered storage."""

    s3_key: str | None = None
    code: IpErrorCode = IpErrorCode.PAYLOAD_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = (
        "Verify that the payload blob exists in tiered storage for the given s3_key."
    )


@dataclass(frozen=True, kw_only=True)
class TenantShardNotFoundError(IpError):
    """Returned when a tenant has no active Data Plane database shard assigned for IP."""

    tenant_id: str = ""
    code: IpErrorCode = IpErrorCode.TENANT_SHARD_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = (
        "Ensure the tenant is subscribed to 'ip' and mapped to an active shard in ucp.shard_registry."
    )

    @classmethod
    def for_tenant(cls, tenant_id: str) -> TenantShardNotFoundError:
        return cls(
            tenant_id=tenant_id,
            message=f"Tenant '{tenant_id}' is not mapped to an active Integration Platform database shard.",
            details={"tenant_id": tenant_id},
        )


@dataclass(frozen=True, kw_only=True)
class ActiveSyncRunAlreadyExistsError(IpError):
    """Returned when a sync run is already PENDING or RUNNING for the given connection and stream."""

    connection_id: str = ""
    stream: str = ""
    code: IpErrorCode = IpErrorCode.ACTIVE_SYNC_RUN_EXISTS
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409
    remediation: str | None = "Wait for the active sync run to finish or cancel it."

    @classmethod
    def for_stream(cls, connection_id: str, stream: str) -> ActiveSyncRunAlreadyExistsError:
        return cls(
            connection_id=connection_id,
            stream=stream,
            message=f"An active sync run is already running for connection '{connection_id}', stream '{stream}'.",
            details={"connection_id": connection_id, "stream": stream},
        )


@dataclass(frozen=True, kw_only=True)
class InboundVerificationFailedError(IpError):
    """Returned when an external webhook fails cryptographic signature or token verification."""

    code: IpErrorCode = IpErrorCode.INBOUND_VERIFICATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 401
    remediation: str | None = "Verify the shared secret, signing algorithm, and webhook headers."


@dataclass(frozen=True, kw_only=True)
class InboundPayloadDecodeError(IpError):
    """Returned when an incoming webhook body cannot be parsed according to its content-type."""

    code: IpErrorCode = IpErrorCode.INBOUND_PAYLOAD_DECODE_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = "Ensure payload matches the advertised Content-Type header."


@dataclass(frozen=True, kw_only=True)
class DuplicateExternalEventError(IpError):
    """Returned when an external push event ID has already been recorded."""

    code: IpErrorCode = IpErrorCode.DUPLICATE_EXTERNAL_EVENT
    disposition: FailureDisposition = FailureDisposition.IGNORE
    http_status: int = 200
    remediation: str | None = "Duplicate event acknowledged as a no-op."


@dataclass(frozen=True, kw_only=True)
class RateLimitExceededError(IpError):
    """Returned when the upstream API responds with HTTP 429 Too Many Requests."""

    code: IpErrorCode = IpErrorCode.RATE_LIMIT_EXCEEDED
    disposition: FailureDisposition = FailureDisposition.RETRY
    http_status: int = 429
    retry_after_seconds: int = 60
    remediation: str | None = "Wait for the Retry-After interval before resuming synchronization."


@dataclass(frozen=True, kw_only=True)
class TransformationNotFoundError(IpError):
    """Returned when a stream transformation configuration does not exist."""

    connection_id: str = ""
    stream: str = ""
    code: IpErrorCode = IpErrorCode.TRANSFORMATION_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Configure a transformation for this stream before normalizing."

    @classmethod
    def for_stream(cls, connection_id: str, stream: str) -> TransformationNotFoundError:
        return cls(
            connection_id=connection_id,
            stream=stream,
            message=f"No transformation configured for connection '{connection_id}', stream '{stream}'.",
            details={"connection_id": connection_id, "stream": stream},
        )


@dataclass(frozen=True, kw_only=True)
class ReplicaRecordNotFoundError(IpError):
    """Returned when a requested replica record cannot be located on the tenant shard."""

    replica_record_id: str = ""
    code: IpErrorCode = IpErrorCode.REPLICA_RECORD_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify that the replica record ID exists."

    @classmethod
    def for_id(cls, replica_record_id: str) -> ReplicaRecordNotFoundError:
        return cls(
            replica_record_id=replica_record_id,
            message=f"Replica record '{replica_record_id}' was not found.",
            details={"replica_record_id": replica_record_id},
        )


@dataclass(frozen=True, kw_only=True)
class NormalizationFailedError(IpError):
    """Returned when an unrecoverable failure occurs during replica normalization."""

    code: IpErrorCode = IpErrorCode.NORMALIZATION_FAILED
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 500
    remediation: str | None = "Check the error details and mapper implementation."

    @classmethod
    def with_message(
        cls, message: str, details: JsonDict | None = None
    ) -> NormalizationFailedError:
        return cls(
            message=message,
            details=details or {},
        )


@dataclass(frozen=True, kw_only=True)
class TraceNotFoundError(IpError):
    """Returned when a requested trace_id cannot be located on the tenant shard."""

    trace_id: str = ""
    code: IpErrorCode = IpErrorCode.TRACE_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify that the trace_id exists and belongs to the active tenant."

    @classmethod
    def for_trace(cls, trace_id: str) -> TraceNotFoundError:
        return cls(
            trace_id=trace_id,
            message=f"Transaction trace '{trace_id}' was not found.",
            details={"trace_id": trace_id},
        )


@dataclass(frozen=True, kw_only=True)
class ReplayStageNotAvailableError(IpError):
    """Returned when a replay is requested at a stage whose source artifacts do not exist for the trace."""

    trace_id: str = ""
    stage: str = ""
    code: IpErrorCode = IpErrorCode.REPLAY_STAGE_NOT_AVAILABLE
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 409
    remediation: str | None = (
        "Select an earlier replay stage (e.g. RETRY_INGEST) that has a persisted source record."
    )

    @classmethod
    def for_stage(cls, trace_id: str, stage: str, reason: str) -> ReplayStageNotAvailableError:
        return cls(
            trace_id=trace_id,
            stage=stage,
            message=reason,
            details={"trace_id": trace_id, "stage": stage},
        )


@dataclass(frozen=True, kw_only=True)
class SyncRunNotFoundError(IpError):
    """Returned when a requested sync run ID cannot be found for the connection and tenant."""

    run_id: str = ""
    code: IpErrorCode = IpErrorCode.SYNC_RUN_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = "Verify the run_id exists and belongs to the active connection."

    @classmethod
    def for_id(cls, run_id: str) -> SyncRunNotFoundError:
        return cls(
            run_id=run_id,
            message=f"Sync run '{run_id}' was not found.",
            details={"run_id": run_id},
        )


@dataclass(frozen=True, kw_only=True)
class TransformerNotFoundError(IpError):
    """Returned when a requested transformer_id and version is not registered in TransformerRegistryPort."""

    transformation_id: str = ""
    transformation_version: int = 1
    code: IpErrorCode = IpErrorCode.TRANSFORMER_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = (
        "Verify the transformation_id and transformation_version against /api/v1/tenants/{tenant_id}/ip/transformations/transformers."
    )

    @classmethod
    def for_version(
        cls, transformation_id: str, transformation_version: int
    ) -> TransformerNotFoundError:
        return cls(
            transformation_id=transformation_id,
            transformation_version=transformation_version,
            message=f"Transformer '{transformation_id}' version {transformation_version} is not registered.",
            details={
                "transformation_id": transformation_id,
                "transformation_version": transformation_version,
            },
        )


@dataclass(frozen=True, kw_only=True)
class StitchDefinitionNotFoundError(IpError):
    """Returned when a requested stitch WorkflowDefinition cannot be found."""

    workflow_id: str = ""
    version: int | None = None
    code: IpErrorCode = IpErrorCode.STITCH_DEFINITION_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = (
        "Verify the workflow_id against /api/v1/tenants/{tenant_id}/ip/stitches/definitions."
    )

    @classmethod
    def for_workflow(
        cls, workflow_id: str, version: int | None = None
    ) -> StitchDefinitionNotFoundError:
        suffix = f" version {version}" if version is not None else ""
        return cls(
            workflow_id=workflow_id,
            version=version,
            message=f"Stitch workflow definition '{workflow_id}'{suffix} was not found.",
            details={"workflow_id": workflow_id, "version": version},
        )


@dataclass(frozen=True, kw_only=True)
class StitchRunNotFoundError(IpError):
    """Returned when a requested stitch WorkflowRun cannot be found on the tenant shard."""

    run_id: str = ""
    code: IpErrorCode = IpErrorCode.STITCH_RUN_NOT_FOUND
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 404
    remediation: str | None = (
        "Verify the stitch workflow run_id exists and belongs to the active tenant."
    )

    @classmethod
    def for_id(cls, run_id: str) -> StitchRunNotFoundError:
        return cls(
            run_id=run_id,
            message=f"Stitch workflow run '{run_id}' was not found.",
            details={"run_id": run_id},
        )


@dataclass(frozen=True, kw_only=True)
class InvalidReplayPayloadError(IpError):
    """Returned when a modified payload supplied to ModifyAndReplay is structurally invalid."""

    trace_id: str = ""
    code: IpErrorCode = IpErrorCode.INVALID_REPLAY_PAYLOAD
    disposition: FailureDisposition = FailureDisposition.FAIL
    http_status: int = 400
    remediation: str | None = "Supply a non-empty JSON object for the modified replay payload."

    @classmethod
    def for_trace(cls, trace_id: str, reason: str) -> InvalidReplayPayloadError:
        return cls(
            trace_id=trace_id,
            message=reason,
            details={"trace_id": trace_id},
        )


__all__ = [
    "ActiveSyncRunAlreadyExistsError",
    "AuthenticationFailedError",
    "CatalogDiscoveryError",
    "ConnectionCheckError",
    "ConnectionDeactivatedError",
    "ConnectionNotFoundError",
    "ConnectorNotFoundError",
    "DuplicateConnectionFingerprintError",
    "DuplicateExternalEventError",
    "EndpointSecurityViolationError",
    "FailureDisposition",
    "InboundPayloadDecodeError",
    "InboundVerificationFailedError",
    "InvalidConnectionConfigError",
    "InvalidConnectionStateError",
    "InvalidCredentialsError",
    "InvalidEndpointError",
    "InvalidReplayPayloadError",
    "IpError",
    "IpErrorCode",
    "ManifestParseFailureError",
    "NormalizationFailedError",
    "PayloadNotFoundError",
    "RateLimitExceededError",
    "ReplayStageNotAvailableError",
    "ReplicaRecordNotFoundError",
    "Result",
    "SftpConnectionError",
    "StitchDefinitionNotFoundError",
    "StitchRunNotFoundError",
    "StreamNotFoundError",
    "SyncRunNotFoundError",
    "TenantShardNotFoundError",
    "TraceNotFoundError",
    "TransformationNotFoundError",
    "TransformerNotFoundError",
    "UnsupportedWriteOperationError",
    "UpstreamHttpError",
    "UpstreamNetworkError",
    "UpstreamRemoteError",
    "WriteActionNotConfiguredError",
]
