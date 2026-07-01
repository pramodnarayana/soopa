import json
from pathlib import Path

from bots_core.facade import edi_to_json, json_to_edi


def test_edifact_round_trip(patch_data_dir: Path):
    edifact_data = """UNA:+.?*'
UNB+utf8:1+SENDER+RECEIVER+071101:1731+1'
UNH+1+ORDERS:D:96A:UN'
BGM+220+12345+9'
DTM+137:20071101:102'
UNT+4+1'
UNZ+1+1'
"""
    input_file = patch_data_dir / "input.edi"
    input_file.write_text(edifact_data)

    # 1. Parse EDI to JSON AST
    json_ast = edi_to_json(str(input_file), editype="edifact", messagetype="edifact")

    # Verify JSON AST
    parsed = json.loads(json_ast)
    assert parsed["children"][0]["record"]["BOTSID"] == "UNB"
    assert parsed["children"][0]["children"][0]["record"]["BOTSID"] == "UNH"

    # 2. Serialize JSON AST back to EDI
    output_edi = json_to_edi(json_ast, editype="edifact", messagetype="edifact")

    # 3. Check that it contains the expected content
    assert "UNB" in output_edi
    assert "UNH" in output_edi
    assert "UNT" in output_edi
