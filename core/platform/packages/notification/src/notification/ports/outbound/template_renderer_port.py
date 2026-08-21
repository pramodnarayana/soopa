from collections.abc import Mapping
from typing import Any, Protocol


class TemplateRendererPort(Protocol):
    def render(self, template_str: str, data: Mapping[str, Any]) -> str: ...
