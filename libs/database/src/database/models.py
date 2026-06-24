"""
SQLAlchemy Models for EDI AS2 Core and Trading Partners.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Tenant(Base):
    """
    Represents an isolated tenant in the Hybrid Tenancy model.
    """

    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TradingPartner(Base):
    """
    Represents an AS2 Trading Partner profile.
    """

    __tablename__ = "trading_partners"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    as2_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(String(1024), nullable=True)  # Destination URL for outgoing messages

    # Public certificate for encrypting payloads sent TO this partner,
    # and verifying signatures received FROM this partner.
    # Public certificate for encrypting payloads sent TO this partner,
    # and verifying signatures received FROM this partner.
    public_cert_pem = Column(Text, nullable=True)

    # For the Server's own identity (Host), we store the private key securely.
    # Regular trading partners will NOT have this field populated.
    is_host_identity = Column(Boolean, default=False, nullable=False)
    private_key_pem = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "as2_id", name="uq_tenant_as2_id"),)


class AS2Payload(Base):
    """
    Storage for incoming and outgoing AS2 Messages and their payloads.
    """

    __tablename__ = "as2_payloads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)

    message_id = Column(String(255), nullable=False, index=True)
    direction = Column(String(10), nullable=False)  # 'INBOUND' or 'OUTBOUND'

    as2_from = Column(String(255), nullable=False)
    as2_to = Column(String(255), nullable=False)

    raw_headers = Column(Text, nullable=True)

    # S3/MinIO/LocalStack URI where the massive binary payload is stored.
    payload_storage_uri = Column(String(2048), nullable=True)

    mic = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False)  # 'RECEIVED', 'DECRYPTED', 'MDN_SENT', 'ERROR'

    created_at = Column(DateTime, default=datetime.utcnow)
