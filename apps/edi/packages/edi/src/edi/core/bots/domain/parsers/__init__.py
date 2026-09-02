"""
parsers/__init__.py — EDI format reader/writer registry.

Imports concrete parser classes THEN registers them into the shared
registry dicts. This ordering is critical: registry.py must be importable
without pulling in any concrete parser, so that outmessage.py and
inmessage.py can import from registry.py without triggering a cycle.
"""

from edi.core.bots.domain.parser_registry import READER_REGISTRY, WRITER_REGISTRY

from .edifact import edifact as EdifactReader
from .edifact import edifact_writer as EdifactWriter
from .x12 import x12 as X12Reader
from .x12 import x12_writer as X12Writer

# Registration happens here, after all concrete classes are fully defined.
READER_REGISTRY["edifact"] = EdifactReader
READER_REGISTRY["x12"] = X12Reader

WRITER_REGISTRY["edifact"] = EdifactWriter
WRITER_REGISTRY["x12"] = X12Writer

__all__ = ["READER_REGISTRY", "WRITER_REGISTRY"]
