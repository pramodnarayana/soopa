from typing import Protocol

from seedwork.domain.types import JsonDict


class TemplateRendererPort(Protocol):
    def render(self, template_str: str, data: JsonDict) -> str: ...
