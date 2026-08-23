# type: ignore
"""
parsers/__init__.py — Registry of EDI format readers and writers.
Replacing the legacy globals()[editype] reflection hack in inmessage.py / outmessage.py.
"""

from typing import Any

from .edifact import edifact as EdifactReader
from .edifact import edifact_writer as EdifactWriter
from .x12 import x12 as X12Reader
from .x12 import x12_writer as X12Writer

READER_REGISTRY: dict[str, type[Any]] = {
    "edifact": EdifactReader,
    "x12": X12Reader,
}

WRITER_REGISTRY: dict[str, type[Any]] = {
    "edifact": EdifactWriter,
    "x12": X12Writer,
}

__all__ = ["READER_REGISTRY", "WRITER_REGISTRY"]
