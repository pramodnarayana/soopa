"""
X12 850 — Purchase Order
"""

FIELD_MAPPING: dict[str, str] = {
    "po_number": "$..BEG.BEG03",
    "po_date": "$..BEG.BEG05",
    "business_reference": "$..BEG.BEG03",
}
