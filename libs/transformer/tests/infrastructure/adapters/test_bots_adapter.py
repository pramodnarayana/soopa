import pytest
from transformer.domain.exceptions import TranslationError
from transformer.infrastructure.adapters.bots_adapter import BotsEDIAdapter

# Sample X12 EDI payload (997 FA)
SAMPLE_X12 = b"""ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *210101*1200*U*00401*000000001*0*P*>~
GS*FA*SENDER*RECEIVER*20210101*1200*1*X*004010~
ST*997*0001~
AK1*PO*1~
AK9*A*1*1*1~
SE*4*0001~
GE*1*1~
IEA*1*000000001~"""

# Sample EDIFACT payload (Empty Envelope)
SAMPLE_EDIFACT = b"""UNA:+.? '
UNB+UNOA:1+SENDER+RECEIVER+210101:1200+1'
UNZ+0+1'"""


@pytest.fixture
def adapter():
    return BotsEDIAdapter()


@pytest.mark.asyncio
async def test_bots_adapter_get_raw_ast(adapter):
    ast_dict, errors = adapter.get_raw_ast(SAMPLE_X12)
    assert not errors
    assert "interchange_ISA" in ast_dict
    assert isinstance(ast_dict["interchange_ISA"], list)


@pytest.mark.asyncio
async def test_bots_adapter_translate_x12(adapter):
    payload = await adapter.translate(SAMPLE_X12)
    assert payload.sender_id == "SENDER"
    assert payload.receiver_id == "RECEIVER"
    assert payload.interchange_control_number in ("1", "000000001")
    assert len(payload.transactions) == 1
    txn = payload.transactions[0]
    assert txn.transaction_type == "997"
    assert txn.control_number == "0001"
    assert "AK101" in txn.data["AK1"]


@pytest.mark.asyncio
async def test_bots_adapter_translate_edifact(adapter):
    # Depending on our domain model extraction for EDIFACT, it might extract different fields
    # Default messagetype='envelope' allows parsing just the UNB/UNZ headers
    payload = await adapter.translate(SAMPLE_EDIFACT, editype="edifact", messagetype="envelope")
    assert payload.sender_id == "SENDER"
    assert payload.receiver_id == "RECEIVER"
    assert payload.interchange_control_number == "1"
    assert len(payload.transactions) == 0


@pytest.mark.asyncio
async def test_bots_adapter_translate_empty_payload(adapter):
    with pytest.raises(TranslationError) as exc:
        await adapter.translate(b"")
    assert "empty" in str(exc.value)


@pytest.mark.asyncio
async def test_bots_adapter_translate_garbage_payload(adapter):
    with pytest.raises(TranslationError) as exc:
        await adapter.translate(b"GARBAGE")
    assert exc.value.errors is not None
    # Since parsing fails outright, it might just have 1 core error about format
    assert len(exc.value.errors) > 0


def test_bots_adapter_serialize_to_edi(adapter):
    # First, get a clean AST
    ast_dict, _ = adapter.get_raw_ast(SAMPLE_X12)

    # Serialize it back to EDI
    edi_str, errors = adapter.serialize_to_edi(ast_dict, standard="x12")
    assert isinstance(edi_str, str)
    assert "ISA*00*" in edi_str
    # Ignore warnings about auto-injected ISA16
    assert not [e for e in errors if not e.startswith("[W")]


def test_bots_adapter_serialize_invalid_ast(adapter):
    ast_dict = {"invalid_root": "yes"}
    edi_str, errors = adapter.serialize_to_edi(ast_dict, standard="x12")
    # For a completely invalid AST, it either raises or returns empty edi_str
    assert edi_str == ""
    assert len(errors) > 0
