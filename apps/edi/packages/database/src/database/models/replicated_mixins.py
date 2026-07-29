from typing import Any
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.sql import func, text


class AS2PartnerMixin:
    """Shared columns for AS2Partner across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def as2_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def public_cert_pem(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def public_cert_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def private_key_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def prev_public_cert_pem(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def prev_public_cert_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def prev_private_key_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def url(cls) -> Mapped[str | None]:
        return mapped_column(String(1024), nullable=True)

    @declared_attr
    def is_local(cls) -> Mapped[bool]:
        return mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))


class AS2PartnershipMixin:
    """Shared columns for AS2Partnership across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def credentials_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def mdn_type(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, default="SYNC")

    @declared_attr
    def mdn_url(cls) -> Mapped[str | None]:
        return mapped_column(String(1024), nullable=True)

    @declared_attr
    def encryption_algorithm(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, default="AES256")

    @declared_attr
    def signature_algorithm(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, default="SHA256")

    @declared_attr
    def advanced_flags(cls) -> Mapped[dict[str, Any] | None]:
        return mapped_column(JSONB, nullable=True)

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))


class SFTPPartnerMixin:
    """Shared columns for SFTPPartner across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def host(cls) -> Mapped[str]:
        return mapped_column(String(1024), nullable=False)

    @declared_attr
    def port(cls) -> Mapped[int]:
        return mapped_column(Integer, default=22)

    @declared_attr
    def username(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def host_key(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def inbound_remote_path(cls) -> Mapped[str | None]:
        return mapped_column(String(1024), nullable=True)

    @declared_attr
    def outbound_remote_path(cls) -> Mapped[str | None]:
        return mapped_column(String(1024), nullable=True)

    @declared_attr
    def password_encrypted(cls) -> Mapped[str | None]:
        return mapped_column(String(1024), nullable=True)

    @declared_attr
    def credentials_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))


class WebhookMixin:
    """Shared columns for Webhook across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[str]:
        return mapped_column(String(128), primary_key=True)

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def url(cls) -> Mapped[str]:
        return mapped_column(String(1024), nullable=False)

    @declared_attr
    def auth_header_vault_ref(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))


class InboundRouteMixin:
    """Shared columns for InboundRoute across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def trading_partner_id(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def isa_sender_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def isa_receiver_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def gs_sender_id(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def gs_receiver_id(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True)

    @declared_attr
    def transaction_type(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False)

    @declared_attr
    def processing_mode(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, server_default="TRANSFORM")

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))


class OutboundEdiHeaderMixin:
    """Configuration for Outbound EDI Headers (Ingestion/Translation Config)."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def trading_partner_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def isa_sender_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def isa_sender_qualifier(cls) -> Mapped[str | None]:
        return mapped_column(String(2), nullable=True)

    @declared_attr
    def isa_receiver_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def isa_receiver_qualifier(cls) -> Mapped[str | None]:
        return mapped_column(String(2), nullable=True)

    @declared_attr
    def gs_sender_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def gs_receiver_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def transaction_type(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False)

    @declared_attr
    def default_standard(cls) -> Mapped[str]:
        return mapped_column(String(50), default="x12", server_default="x12")

    @declared_attr
    def default_version(cls) -> Mapped[str]:
        return mapped_column(String(50), default="004010", server_default="004010")


class OutboundRouteMixin:
    """Shared columns for OutboundRoute (Delivery Config) across Global and Tenant schemas."""

    @declared_attr
    def id(cls) -> Mapped[PyUUID]:
        return mapped_column(
            UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
        )

    @declared_attr
    def trading_partner_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def name(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def protocol(cls) -> Mapped[str]:
        return mapped_column(String(50), nullable=False, server_default="AS2")

    @declared_attr
    def active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default=text("false"))
