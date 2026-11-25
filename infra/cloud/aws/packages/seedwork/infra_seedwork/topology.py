"""
infra_seedwork.topology
=======================
Single source of truth loader for topology.json.

All IaC stacks MUST use ``load_topology()`` from this module rather than
constructing fragile relative paths to topology.json themselves. This
eliminates the class of bugs where a directory reorganisation silently breaks
the path resolution without any compile-time or runtime warning.
"""

import json
from pathlib import Path
from typing import cast

from infra_seedwork.messaging import TopologyConfig


def load_topology() -> TopologyConfig:
    """
    Walks up the directory tree from the infra_seedwork package location to
    find ``topology.json`` at the repository root.

    The repo root is identified as the directory containing ``topology.json``.
    We search up to 12 parent directories to accommodate any nesting depth.

    Returns:
        Parsed topology dict with keys: topics, queues, subscriptions, etc.

    Raises:
        FileNotFoundError: If topology.json is not found within 12 parent dirs.
    """
    current = Path(__file__).resolve().parent
    for _ in range(12):
        candidate = current / "topology.json"
        if candidate.is_file():
            with open(candidate, encoding="utf-8") as f:
                return cast(TopologyConfig, json.load(f))
        current = current.parent
    raise FileNotFoundError(
        "topology.json not found within 12 parent directories of infra_seedwork. "
        "Ensure the file exists at the repository root."
    )
