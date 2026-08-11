"""Unit tests for Jinja2TemplateRenderer.

Covers:
- Variable interpolation for all three channels (EMAIL, SLACK, IN_APP).
- Conditional logic and loops inside templates.
- SSTI attack vector prevention via SandboxedEnvironment.
- Graceful silent handling of undefined variables.
- Subject rendering.
"""

import pytest
from jinja2.exceptions import SecurityError

from notification_engine.adapters.outbound.template_renderer import Jinja2TemplateRenderer


@pytest.fixture()
def renderer() -> Jinja2TemplateRenderer:
    return Jinja2TemplateRenderer()


class TestBasicInterpolation:
    def test_renders_simple_variable(self, renderer: Jinja2TemplateRenderer) -> None:
        result = renderer.render("Hello, {{ name }}!", {"name": "Alice"})
        assert result == "Hello, Alice!"

    def test_renders_multiple_variables(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = "Tenant {{ tenant_id }} — event {{ event_type }} fired."
        result = renderer.render(tmpl, {"tenant_id": "ten_123", "event_type": "invoice.failed"})
        assert result == "Tenant ten_123 — event invoice.failed fired."

    def test_renders_subject_template(self, renderer: Jinja2TemplateRenderer) -> None:
        result = renderer.render("Invoice #{{ invoice_id }} Ready", {"invoice_id": "INV-999"})
        assert result == "Invoice #INV-999 Ready"


class TestChannelSpecificTemplates:
    """Templates are channel-agnostic; Jinja2 renders any string format."""

    def test_email_html_template(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = "<h1>Hello {{ user_name }}</h1><p>Your invoice {{ amount }} is due.</p>"
        result = renderer.render(tmpl, {"user_name": "Bob", "amount": "$500"})
        assert "<h1>Hello Bob</h1>" in result
        assert "<p>Your invoice $500 is due.</p>" in result

    def test_slack_block_kit_json_template(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = '{"text": "Alert: {{ event_type }} for tenant {{ tenant_id }}"}'
        result = renderer.render(tmpl, {"event_type": "payment.failed", "tenant_id": "ten_abc"})
        assert result == '{"text": "Alert: payment.failed for tenant ten_abc"}'

    def test_in_app_plain_text_template(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = "Your webhook {{ webhook_name }} has failed {{ failure_count }} times."
        result = renderer.render(tmpl, {"webhook_name": "OrderCreated", "failure_count": 3})
        assert result == "Your webhook OrderCreated has failed 3 times."


class TestJinja2Logic:
    def test_conditional_renders_correctly_when_true(
        self, renderer: Jinja2TemplateRenderer
    ) -> None:
        tmpl = "Status: {% if is_critical %}CRITICAL{% else %}Normal{% endif %}"
        assert renderer.render(tmpl, {"is_critical": True}) == "Status: CRITICAL"
        assert renderer.render(tmpl, {"is_critical": False}) == "Status: Normal"

    def test_for_loop_renders_list(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = "Items:{% for item in items %} {{ item }}{% endfor %}"
        result = renderer.render(tmpl, {"items": ["A", "B", "C"]})
        assert result == "Items: A B C"

    def test_nested_attribute_access(self, renderer: Jinja2TemplateRenderer) -> None:
        tmpl = "Invoice {{ invoice.id }} for {{ invoice.amount }}"
        result = renderer.render(tmpl, {"invoice": {"id": "INV-1", "amount": "$200"}})
        assert result == "Invoice INV-1 for $200"


class TestUndefinedVariables:
    def test_missing_variable_renders_as_empty_string(
        self, renderer: Jinja2TemplateRenderer
    ) -> None:
        """Missing variables must silently render to '' to avoid crashing the delivery pipeline."""
        result = renderer.render("Hello {{ missing_var }}!", {})
        assert result == "Hello !"

    def test_partial_missing_renders_available_vars(self, renderer: Jinja2TemplateRenderer) -> None:
        result = renderer.render("{{ present }} and {{ absent }}", {"present": "exists"})
        assert result == "exists and "


class TestSSTISecurityHardening:
    """
    CRITICAL: Validate that the SandboxedEnvironment blocks all known SSTI
    attack vectors that a malicious tenant admin could inject into a template.
    """

    def test_class_introspection_blocked(self, renderer: Jinja2TemplateRenderer) -> None:
        """Block access to Python's class hierarchy from within a template."""
        attack = "{{ ''.__class__.__mro__ }}"
        with pytest.raises(SecurityError):
            renderer.render(attack, {})

    def test_subclasses_escape_blocked(self, renderer: Jinja2TemplateRenderer) -> None:
        """Block subclass enumeration — a classic Python SSTI gadget chain."""
        attack = "{{ ''.__class__.__mro__[1].__subclasses__() }}"
        with pytest.raises(SecurityError):
            renderer.render(attack, {})

    def test_builtins_access_blocked(self, renderer: Jinja2TemplateRenderer) -> None:
        """Block access to Python builtins from within a template."""
        attack = "{{ ''.__class__.__init__.__globals__['__builtins__'] }}"
        with pytest.raises(SecurityError):
            renderer.render(attack, {})

    def test_os_module_access_blocked(self, renderer: Jinja2TemplateRenderer) -> None:
        """Block any attempt to import os or run system commands."""
        attack = "{{ self.__init__.__globals__['os'].listdir('.') }}"
        with pytest.raises(SecurityError):
            renderer.render(attack, {})
