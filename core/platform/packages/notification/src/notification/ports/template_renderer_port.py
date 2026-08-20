from typing import Any, Protocol


class TemplateRendererPort(Protocol):
    def render(self, template_str: str, data: dict[str, Any]) -> str: ...
