from unified_api.adapters.inbound.http.dtos.tenant_dtos import ProvisionTenantRequest


def test_provision_tenant_request_requires_only_name() -> None:
    request = ProvisionTenantRequest(name="Acme")

    assert request.name == "Acme"
    assert set(ProvisionTenantRequest.model_fields) == {"name"}
