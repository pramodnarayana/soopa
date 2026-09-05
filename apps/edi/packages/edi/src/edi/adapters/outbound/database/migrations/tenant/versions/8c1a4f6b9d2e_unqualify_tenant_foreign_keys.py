"""Unqualify AS2 partnership foreign keys.

Revision ID: 8c1a4f6b9d2e
Revises: d09f3e74ebd0
Create Date: 2026-09-04

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c1a4f6b9d2e"
down_revision: str | Sequence[str] | None = "d09f3e74ebd0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FOREIGN_KEYS = (
    (
        "as2_partnerships_local_partner_id_fkey",
        "as2_partnerships",
        "local_partner_id",
        "as2_partners",
        "CASCADE",
    ),
    (
        "as2_partnerships_remote_partner_id_fkey",
        "as2_partnerships",
        "remote_partner_id",
        "as2_partners",
        "CASCADE",
    ),
)


def _replace_foreign_keys(referent_schema: str | None) -> None:
    for name, source_table, source_column, referent_table, ondelete in _FOREIGN_KEYS:
        op.drop_constraint(name, source_table, type_="foreignkey")
        op.create_foreign_key(
            name,
            source_table,
            referent_table,
            [source_column],
            ["id"],
            referent_schema=referent_schema,
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Point tenant foreign keys at tables in the active tenant schema."""
    _replace_foreign_keys(referent_schema=None)


def downgrade() -> None:
    """Restore the original edi-qualified foreign-key targets."""
    _replace_foreign_keys(referent_schema="edi")
