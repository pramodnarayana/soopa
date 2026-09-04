from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from edi.adapters.outbound.database.models.data_plane import EdiMessage
from edi.adapters.outbound.database.transaction_repository import SqlAlchemyTransactionRepository


def test_trading_partner_neq_filter_includes_null_identifiers() -> None:
    repository = object.__new__(SqlAlchemyTransactionRepository)
    statement = repository._apply_dynamic_filters(
        select(EdiMessage),
        EdiMessage,
        [{"field": "trading_partner_id", "operator": "neq", "value": "partner-1"}],
    )

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    for column in (
        "sender_id",
        "receiver_id",
        "gs_sender_id",
        "gs_receiver_id",
        "trading_partner_id",
    ):
        expected = f"(edi_messages.{column} IS NULL OR edi_messages.{column} != 'partner-1')"
        assert expected in sql
