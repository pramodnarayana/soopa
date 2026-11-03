from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from edi.adapters.outbound.database.data_plane.edi_message_repository import (
    SqlAlchemyEdiMessageRepository,
)
from edi.adapters.outbound.database.models.data_plane import EdiMessage
from edi.domain.transaction.stage_filter import (
    FilterOperator,
    StageFilterCriterion,
    StageFilterTarget,
)


def test_trading_partner_neq_filter_includes_null_identifiers() -> None:
    repository = object.__new__(SqlAlchemyEdiMessageRepository)
    statement = repository._apply_dynamic_filters(
        select(EdiMessage),
        EdiMessage,
        [
            StageFilterCriterion(
                field="trading_partner_id",
                operator=FilterOperator.NEQ,
                value="partner-1",
            )
        ],
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


def test_stage_filter_criterion_rejects_edi_json_unsupported_fields_via_result() -> None:
    res = StageFilterCriterion.create(
        field="sender_id",
        operator="eq",
        value="SND-1",
        target=StageFilterTarget.EDI_JSON,
    )
    assert res.is_err
    assert "not supported for EdiJson" in res.unwrap_err().message
