from collections.abc import Iterator, Mapping
from functools import lru_cache
from typing import Any

from jinja2 import ChainableUndefined, Template
from jinja2.sandbox import SandboxedEnvironment


class _SilentUndefined(ChainableUndefined):
    """Renders undefined variables as empty string instead of raising an error.

    This ensures a missing template variable never crashes the delivery
    pipeline; the missing token simply becomes an empty string in the output.
    """

    def __str__(self) -> str:
        return ""

    def __iter__(self) -> Iterator[Any]:
        return iter([])

    def __bool__(self) -> bool:
        return False


class Jinja2TemplateRenderer:
    """Adapter that satisfies TemplateRendererPort using Jinja2 SandboxedEnvironment.

    Security note: All tenant-supplied templates are compiled inside a
    ``SandboxedEnvironment``.  This prevents arbitrary code execution
    (SSTI) even when tenant admins craft malicious Jinja2 expressions such as
    ``{{ ''.__class__.__mro__[1].__subclasses__() }}``.
    """

    def __init__(self) -> None:
        self._env = SandboxedEnvironment(
            undefined=_SilentUndefined,
            autoescape=False,  # Templates control escaping per channel
        )
        # Compile and cache templates by source string to avoid repeated parsing
        self._compile_template = lru_cache(maxsize=512)(self._compile_template_uncached)

    def _compile_template_uncached(self, template_str: str) -> Template:
        """Compile a template string into a Jinja2 Template object."""
        return self._env.from_string(template_str)

    def render(self, template_str: str, data: Mapping[str, Any]) -> str:
        template = self._compile_template(template_str)
        return template.render(**data)
