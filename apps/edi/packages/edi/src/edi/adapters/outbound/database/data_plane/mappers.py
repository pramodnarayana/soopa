from edi.adapters.outbound.database.models.data_plane import AS2Partner as OrmAS2Partner
from edi.domain.partner.as2.partner import AS2Partner


def as2_partner_to_domain(record: OrmAS2Partner) -> AS2Partner:
    """Explicit data-plane mapper from SQLAlchemy AS2Partner record to domain AS2Partner."""
    return AS2Partner(
        id=record.id,
        as2_id=record.as2_id,
        name=record.name,
        is_local=record.is_local,
        created_at=record.created_at,
        updated_at=record.updated_at,
        tenant_id=record.tenant_id,
        public_cert_pem=record.public_cert_pem,
        public_cert_vault_ref=record.public_cert_vault_ref,
        private_key_vault_ref=record.private_key_vault_ref,
        prev_public_cert_pem=record.prev_public_cert_pem,
        prev_public_cert_vault_ref=record.prev_public_cert_vault_ref,
        prev_private_key_vault_ref=record.prev_private_key_vault_ref,
        url=record.url,
        active=record.active,
    )
