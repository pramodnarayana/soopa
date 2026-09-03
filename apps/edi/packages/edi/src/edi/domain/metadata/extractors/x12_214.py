"""
X12 214 — Transportation Carrier Shipment Status Message
"""

FIELD_MAPPING: dict[str, str] = {
    "load_number": "$..B10.B1002",
    "business_reference": "$..B10.B1002",
}
