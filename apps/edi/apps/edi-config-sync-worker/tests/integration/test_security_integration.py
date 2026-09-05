import pytest
from edi.adapters.outbound.security.network import get_safe_ip

pytestmark = pytest.mark.integration


def test_public_hostname_resolves_with_live_dns() -> None:
    assert get_safe_ip("example.com") is not None
