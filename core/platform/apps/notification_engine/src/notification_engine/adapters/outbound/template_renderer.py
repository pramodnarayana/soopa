from typing import Any

from jinja2 import BaseLoader, Environment


class Jinja2TemplateRenderer:
    def __init__(self) -> None:
        self.env = Environment(loader=BaseLoader())

    def render(self, template_str: str, data: dict[str, Any]) -> str:
        template = self.env.from_string(template_str)
        return template.render(**data)
