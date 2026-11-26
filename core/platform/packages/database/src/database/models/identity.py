"""SQLAlchemy ORM models for the IdP-Agnostic Identity & Authorization bounded context."""

from __future__ import annotations

from datetime import UTC, datetime

from identity.domain.constants import (
    AuthzEffect,
    IdentityIdPrefix,
    MembershipScope,
    MembershipStatus,
    PolicyEngineType,
    TenantIsolationMode,
    TenantTierType,
)
from seedwork.domain.types import JsonDict
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from database.models.common import OutboxMixin, SoftDeleteMixin
from database.models.core import IdentityBase

_EPOCH_ZERO = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_ZERO_SQL = "'1970-01-01 00:00:00+00'"


class Ltree(UserDefinedType[str]):
    """PostgreSQL `ltree` materialized-path type for N-tier multi-tenant hierarchies."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        del kw
        return "ltree"


class Tenant(IdentityBase, SoftDeleteMixin):
    __tablename__ = "tenants"
    ID_PREFIX = IdentityIdPrefix.TENANT.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    parent_tenant_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    hierarchy_path: Mapped[str | None] = mapped_column(Ltree(), nullable=True)
    tier_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TenantTierType.ORGANIZATION.value,
        server_default=text(f"'{TenantTierType.ORGANIZATION.value}'"),
    )
    isolation_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TenantIsolationMode.POOLED_REALM.value,
        server_default=text(f"'{TenantIsolationMode.POOLED_REALM.value}'"),
    )
    idp_realm_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    block_parent_inheritance: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    tokens_valid_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: _EPOCH_ZERO,
        server_default=text(_EPOCH_ZERO_SQL),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_tenants_status"),
        Index("ix_tenants_parent_status", "parent_tenant_id", "status"),
        Index(
            "ix_tenants_hierarchy_path_gist",
            "hierarchy_path",
            postgresql_using="gist",
        ),
        Index(
            "uq_tenants_dedicated_idp_realm",
            "idp_realm_name",
            unique=True,
            postgresql_where=text(
                f"isolation_mode = '{TenantIsolationMode.DEDICATED_IDP_ORG.value}'"
                " AND idp_realm_name IS NOT NULL"
                " AND deleted_at IS NULL"
            ),
        ),
        {"schema": "identity"},
    )


class User(IdentityBase, SoftDeleteMixin):
    __tablename__ = "users"
    ID_PREFIX = IdentityIdPrefix.USER.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    idp_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    tokens_valid_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: _EPOCH_ZERO,
        server_default=text(_EPOCH_ZERO_SQL),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
        Index("uq_users_email_lower", func.lower(email), unique=True),
        {"schema": "identity"},
    )


class ExternalIdentity(IdentityBase):
    """IdP-agnostic composite link table mapping `(idp_issuer, idp_subject) -> canonical user_id`."""

    __tablename__ = "external_identities"
    ID_PREFIX = IdentityIdPrefix.EXTERNAL_IDENTITY.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idp_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    idp_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    idp_realm_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_external_identities_issuer_subject",
            "idp_issuer",
            "idp_subject",
            unique=True,
            postgresql_include=["user_id"],
        ),
        {"schema": "identity"},
    )


class TrustedIssuer(IdentityBase):
    """Allowlisted OIDC token issuers verified by the multi-issuer JWKS verifier."""

    __tablename__ = "trusted_issuers"

    issuer: Mapped[str] = mapped_column(String(255), primary_key=True)
    jwks_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    jwks_host_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_audiences: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = ({"schema": "identity"},)


class EmailDomainRoute(IdentityBase):
    """Verified domain Home Realm Discovery (HRD) and Enterprise SSO enforcement route."""

    __tablename__ = "email_domain_routes"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idp_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    idp_realm_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sso_enforced: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = ({"schema": "identity"},)


class TenantUser(IdentityBase):
    """Tenant membership ledger (strictly membership/scope/status/TTL — roles live in user_roles)."""

    __tablename__ = "tenant_users"

    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=MembershipScope.DIRECT.value,
        server_default=text(f"'{MembershipScope.DIRECT.value}'"),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MembershipStatus.ACTIVE.value,
        server_default=text(f"'{MembershipStatus.ACTIVE.value}'"),
    )
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_tenant_users_tenant_status", "tenant_id", "status"),
        {"schema": "identity"},
    )


class ApiToken(IdentityBase, SoftDeleteMixin):
    """Platform-managed API keys for machine-to-machine (ERP -> Platform) authentication."""

    __tablename__ = "api_tokens"
    ID_PREFIX = IdentityIdPrefix.TOKEN.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = ({"schema": "identity"},)


class ApiKey(IdentityBase, SoftDeleteMixin):
    """Platform-managed scoped API keys."""

    __tablename__ = "api_keys"
    ID_PREFIX = IdentityIdPrefix.KEY.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    active: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = ({"schema": "identity"},)


class Role(IdentityBase, SoftDeleteMixin):
    __tablename__ = "roles"
    ID_PREFIX = IdentityIdPrefix.ROLE.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    deny_capabilities: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index(
            "uix_roles_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": "identity"},
    )


class UserRole(IdentityBase):
    __tablename__ = "user_roles"

    ID_PREFIX = IdentityIdPrefix.USER_ROLE.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("identity.roles.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index(
            "uix_user_roles_tenant_user_role",
            "tenant_id",
            "user_id",
            "role_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_user_roles_user_tenant_covering",
            "user_id",
            "tenant_id",
            postgresql_include=["role_id", "expires_at"],
        ),
        {"schema": "identity"},
    )


class ResourceGrant(IdentityBase):
    """Zanzibar-inspired ReBAC relationship tuple table (O(log N) covering lookup at 100M+ rows)."""

    __tablename__ = "resource_grants"
    ID_PREFIX = IdentityIdPrefix.RESOURCE_GRANT.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    effect: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AuthzEffect.ALLOW.value,
        server_default=text(f"'{AuthzEffect.ALLOW.value}'"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        Index(
            "ix_resource_grants_lookup_covering",
            "tenant_id",
            "resource_type",
            "resource_id",
            "subject_type",
            "subject_id",
            postgresql_include=["relation", "effect", "expires_at"],
        ),
        {"schema": "identity"},
    )


class PolicyRule(IdentityBase):
    """Custom tenant ABAC or Casdoor-synced Casbin PERM policy rule."""

    __tablename__ = "policy_rules"
    ID_PREFIX = IdentityIdPrefix.POLICY_RULE.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("identity.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    engine_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=PolicyEngineType.ABAC.value,
        server_default=text(f"'{PolicyEngineType.ABAC.value}'"),
    )
    effect: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=AuthzEffect.ALLOW.value,
        server_default=text(f"'{AuthzEffect.ALLOW.value}'"),
    )
    subject_expr: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    action_pattern: Mapped[str] = mapped_column(String(128), nullable=False)
    condition_json: Mapped[JsonDict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_policy_rules_tenant_active_priority", "tenant_id", "is_active", "priority"),
        {"schema": "identity"},
    )


class IdentityOutbox(IdentityBase, OutboxMixin):
    __tablename__ = "outbox"
    ID_PREFIX = IdentityIdPrefix.IDENTITY_OUTBOX.value

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)

    __table_args__ = (
        Index(
            "ix_identity_outbox_pending",
            "status",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        {"schema": "identity"},
    )

    @property
    def body(self) -> JsonDict:
        """Alias for payload to satisfy OutboxEvent protocol."""
        return self.payload


class Capability(IdentityBase):
    """Catalog of all discrete capabilities/permissions available across the platform."""

    __tablename__ = "capabilities"

    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_mfa: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    machine_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    tier_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="TENANT", server_default=text("'TENANT'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_capabilities_domain_resource", "domain", "resource"),
        {"schema": "identity"},
    )
