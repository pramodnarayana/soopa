"""
parser_registry.py — Central, import-safe registry for EDI format readers and writers.

This module lives OUTSIDE the parsers package intentionally. Python loads
a package's __init__.py when ANY submodule of that package is imported.
Placing the registry here means that inmessage.py and outmessage.py can
import READER_REGISTRY / WRITER_REGISTRY without triggering
parsers/__init__.py (which loads edifact.py → base.py → inmessage.py).

The concrete classes are registered into these dicts by parsers/__init__.py
after all concrete parser classes have been fully defined.
"""

READER_REGISTRY: dict[str, type[object]] = {}
WRITER_REGISTRY: dict[str, type[object]] = {}

__all__ = ["READER_REGISTRY", "WRITER_REGISTRY"]
