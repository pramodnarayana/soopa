"""
X12 204 — Motor Carrier Load Tender
"""

FIELD_MAPPING: dict[str, str] = {
    "load_number": "$..B2.B204",
    "business_reference": "$..B2.B204",
}
