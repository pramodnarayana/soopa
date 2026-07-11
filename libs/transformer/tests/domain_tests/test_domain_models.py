from transformer.domain.models import MappingRule, ParsedEdiPayload, TransactionSet


def test_parsed_edi_payload_instantiation():
    """Validates pure domain model constraints and typing without mocks."""
    transaction = TransactionSet(
        transaction_type="850", control_number="0001", data={"po_number": "12345"}
    )

    payload = ParsedEdiPayload(
        sender_id="SENDER",
        receiver_id="RECEIVER",
        interchange_control_number="1",
        transactions=[transaction],
    )

    assert payload.sender_id == "SENDER"
    assert len(payload.transactions) == 1
    assert payload.transactions[0].transaction_type == "850"


def test_mapping_rule_instantiation():
    """Validates the MappingRule domain entity."""
    rule = MappingRule(source_path="$.ISA[0]", target_path="$.sender")
    assert rule.transformation_type == "DIRECT"
    assert rule.source_path == "$.ISA[0]"
