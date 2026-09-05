"""
X12 210 — Motor Carrier Freight Details and Invoice
"""

FIELD_MAPPING: dict[str, str] = {
    "invoice_number": "$..B3.B302",
    "business_reference": "$..B3.B302",
}
