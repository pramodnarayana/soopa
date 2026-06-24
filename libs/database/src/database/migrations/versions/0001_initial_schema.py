"""Initial schema: tenants, trading_partners, as2_payloads

Revision ID: 0001
Revises:
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tenants',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'trading_partners',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('as2_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=True),
        sa.Column('public_cert_pem', sa.Text(), nullable=True),
        sa.Column('is_host_identity', sa.Boolean(), nullable=False, default=False),
        sa.Column('private_key_pem', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'as2_id', name='uq_tenant_as2_id'),
    )

    op.create_table(
        'as2_payloads',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('as2_from', sa.String(length=255), nullable=False),
        sa.Column('as2_to', sa.String(length=255), nullable=False),
        sa.Column('raw_headers', sa.Text(), nullable=True),
        sa.Column('payload_storage_uri', sa.String(length=2048), nullable=True),
        sa.Column('mic', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_as2_payloads_message_id', 'as2_payloads', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_as2_payloads_message_id', table_name='as2_payloads')
    op.drop_table('as2_payloads')
    op.drop_table('trading_partners')
    op.drop_table('tenants')
