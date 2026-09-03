"""
X12 810 — Invoice
"""

FIELD_MAPPING: dict[str, str] = {
    "invoice_number": "$..BIG.BIG02",
    "po_number": "$..BIG.BIG04",
    "business_reference": "$..BIG.BIG02",
}
