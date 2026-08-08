from dataclasses import dataclass


@dataclass
class App:
    """Domain model representing a Platform Application (e.g. EDI, Core)."""

    id: str
    slug: str
    name: str
    description: str
