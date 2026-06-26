import json
import os
import tempfile

from bots_core.facade import edi_to_json, json_to_edi
from bots_core.utils.botslib import botsglobal


def setup_mock_data_dir(tmp_path):
    """Patch botsglobal.ini.get so that abspathdata resolves under tmp_path."""
    data_dir = str(tmp_path)

    def patched_get(section, key, fallback=""):
        if section == "directories" and key == "data":
            return data_dir
        return fallback

    botsglobal.ini.get = patched_get  # type: ignore[method-assign]


def test_pure_parsing_integration(tmp_path):
    # Create a dummy EDI file
    # A perfect 106-character ISA segment
    edi_content = (
        "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        "*210101*1200*U*00401*000000001*0*T*>~"
        "GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~"
        "ST*850*0001~"
        "BEG*00*SA*123456~"
        "PO1*1*100*EA*10.5~"
        "PO1*2*200*EA*20.5~"
        "CTT*2~"
        "SE*6*0001~"
        "GE*1*1~"
        "IEA*1*000000001~"
    )

    test_file = tmp_path / "test.edi"
    test_file.write_text(edi_content)

    setup_mock_data_dir(tmp_path)

    # Run the pure parser
    # We pass the editype as the messagetype for enveloped formats like x12
    json_result = edi_to_json(str(test_file), editype="x12", messagetype="x12")

    # Verify the JSON output contains the correct structure
    ast = json.loads(json_result)

    # Root has 1 child: the ISA envelope
    isa_node = ast["children"][0]
    assert "BOTSID" in isa_node["record"]
    assert isa_node["record"]["BOTSID"] == "ISA"
    assert isa_node["record"]["ISA06"].strip() == "SENDER"

    # ISA has 2 children: GS and IEA
    assert len(isa_node["children"]) == 2
    gs_node = isa_node["children"][0]
    assert gs_node["record"]["BOTSID"] == "GS"

    # GS has 2 children: ST and GE
    assert len(gs_node["children"]) == 2
    st_node = gs_node["children"][0]
    assert st_node["record"]["BOTSID"] == "ST"

    # ST has 5 children: BEG, PO1, PO1, CTT, SE (the subtranslation!)
    assert len(st_node["children"]) == 5
    assert st_node["children"][0]["record"]["BOTSID"] == "BEG"
    assert st_node["children"][1]["record"]["BOTSID"] == "PO1"
    assert st_node["children"][2]["record"]["BOTSID"] == "PO1"
    assert st_node["children"][3]["record"]["BOTSID"] == "CTT"
    assert st_node["children"][4]["record"]["BOTSID"] == "SE"

    # Check that PO1 loops are parsed
    po1_count = sum(1 for child in st_node["children"] if child["record"]["BOTSID"] == "PO1")
    assert po1_count == 2


def test_pure_generation_integration():
    """
    Test that the stateless EDI generator correctly reverses the JSON AST
    back into a syntactically valid EDI string, correctly respecting Subtranslations.
    """
    edi_content = (
        "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
        "*210101*1200*U*00401*000000001*0*T*>~\r\n"
        "GS*PO*SENDER*RECEIVER*20210101*1200*1*X*004010~\r\n"
        "ST*850*0001~\r\n"
        "BEG*00*SA*123456~\r\n"
        "PO1*1*100*EA*10.5~\r\n"
        "PO1*2*200*EA*20.5~\r\n"
        "CTT*2~\r\n"
        "SE*6*0001~\r\n"
        "GE*1*1~\r\n"
        "IEA*1*000000001~\r\n"
    )

    with tempfile.NamedTemporaryFile("w+", suffix=".edi", delete=False) as f:
        f.write(edi_content)
        temp_path = f.name

    try:
        setup_mock_data_dir(os.path.dirname(temp_path))
        # 1. Parse EDI to JSON AST
        json_result = edi_to_json(temp_path, editype="x12", messagetype="x12")

        # 2. Generate EDI from JSON AST
        edi_result = json_to_edi(json_result, editype="x12", messagetype="x12")

        # 3. Assert Output matches expected EDI Structure
        assert "ISA*00*" in edi_result
        assert "ST*850*0001~" in edi_result
        assert "BEG*00*SA*123456~" in edi_result
        assert "PO1*1*100*EA*10.5~" in edi_result
        assert "SE*6*0001~" in edi_result

    finally:
        os.unlink(temp_path)
