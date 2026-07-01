import json
from pathlib import Path

from bots_core.facade import edi_to_json, json_to_edi


def test_edifact_round_trip(tmp_path: Path):
    edifact_data = """UNA:+.?*'
UNB+utf8:1+SENDER+RECEIVER+071101:1731+1'
UNH+1+ORDERS:D:96A:UN'
BGM+220+12345+9'
DTM+137:20071101:102'
UNT+4+1'
UNZ+1+1'
"""
    input_file = tmp_path / "input.edi"
    input_file.write_text(edifact_data)

    from bots_core.utils.botslib import botsglobal

    orig_get = botsglobal.ini.get

    def patched_get(section, key, fallback=""):
        if section == "directories" and key == "data":
            return str(tmp_path)
        return orig_get(section, key, fallback)

    botsglobal.ini.get = patched_get

    try:
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
    finally:
        botsglobal.ini.get = orig_get
