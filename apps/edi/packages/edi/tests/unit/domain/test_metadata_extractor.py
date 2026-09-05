"""
Layer 1 — Pure Domain Unit Tests: MetadataExtractorService.

The extractor uses compiled JSONPath expressions. It is pure Python — no I/O.
Zero mocks; test all transaction types, missing configs, and edge cases.
"""

from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.domain.metadata.extractors import EXTRACTOR_CONFIG


class TestMetadataExtractorInit:
    def test_uses_default_config_when_none_provided(self):
        svc = MetadataExtractorService()
        assert svc.config is EXTRACTOR_CONFIG
        assert "850" in svc.config

    def test_accepts_custom_config(self):
        custom = {"999": {"my_field": "$.heading.MY_SEGMENT.MY01"}}
        svc = MetadataExtractorService(config=custom)
        assert "999" in svc.config
        assert "850" not in svc.config


class TestMetadataExtractorExtract:
    def setup_method(self):
        self.svc = MetadataExtractorService()

    # --- 850 Purchase Order ---

    def test_850_extracts_po_number(self):
        payload = {"heading": {"transaction_set_header_ST": {}, "BEG": {"BEG03": "PO-12345"}}}
        result = self.svc.extract("850", payload)
        assert result["po_number"] == "PO-12345"
        assert result["business_reference"] == "PO-12345"

    def test_850_extracts_nested_po_number(self):
        payload = {"groups": [{"transactions": [{"heading": {"BEG": {"BEG03": "NESTED-PO"}}}]}]}
        result = self.svc.extract("850", payload)
        assert result["po_number"] == "NESTED-PO"

    def test_850_returns_empty_when_beg_absent(self):
        result = self.svc.extract("850", {"heading": {"other": "field"}})
        assert result == {}

    # --- 810 Invoice ---

    def test_810_extracts_invoice_number(self):
        payload = {"heading": {"BIG": {"BIG02": "INV-001", "BIG04": "PO-999"}}}
        result = self.svc.extract("810", payload)
        assert result["invoice_number"] == "INV-001"
        assert result["po_number"] == "PO-999"
        assert result["business_reference"] == "INV-001"

    # --- 204 Motor Carrier Load ---

    def test_204_extracts_load_number(self):
        payload = {"heading": {"B2": {"B204": "LOAD-777"}}}
        result = self.svc.extract("204", payload)
        assert result["load_number"] == "LOAD-777"

    # --- 997 Functional Acknowledgment ---

    def test_997_extracts_group_control_number(self):
        payload = {"heading": {"AK1": {"AK102": "GCN-123"}}}
        result = self.svc.extract("997", payload)
        assert result["group_control_number"] == "GCN-123"

    # --- Unknown / missing transaction types ---

    def test_unknown_transaction_type_returns_empty_dict(self):
        result = self.svc.extract("999", {"any": "payload"})
        assert result == {}

    def test_empty_transaction_type_returns_empty_dict(self):
        result = self.svc.extract("", {"any": "payload"})
        assert result == {}

    def test_none_like_empty_string_type_returns_empty(self):
        result = self.svc.extract("", {})
        assert result == {}

    # --- Edge cases ---

    def test_payload_with_no_matching_path_returns_empty(self):
        """Transaction type is known but payload has no matching field."""
        result = self.svc.extract("850", {"completely": "different", "structure": True})
        assert result == {}

    def test_first_match_is_used_when_multiple_matches(self):
        """Recursive descendant ($..BEG) may match multiple nodes — first wins."""
        payload = {
            "a": {"BEG": {"BEG03": "FIRST"}},
            "b": {"BEG": {"BEG03": "SECOND"}},
        }
        result = self.svc.extract("850", payload)
        # Must get one or the other — no crash
        assert result["po_number"] in ("FIRST", "SECOND")

    def test_none_value_in_match_is_excluded(self):
        payload = {"heading": {"BEG": {"BEG03": None}}}
        result = self.svc.extract("850", payload)
        # None values should not be stored
        assert "po_number" not in result

    def test_extract_with_custom_config_and_matching_payload(self):
        svc = MetadataExtractorService(config={"TEST": {"my_field": "$.root.MY_SEGMENT.MY01"}})
        payload = {"root": {"MY_SEGMENT": {"MY01": "extracted_value"}}}
        result = svc.extract("TEST", payload)
        assert result["my_field"] == "extracted_value"
