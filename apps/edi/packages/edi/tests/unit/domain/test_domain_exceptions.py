"""
Layer 1 — Pure Domain Unit Tests: EDI Domain Exceptions.

All exception classes are pure Python — instantiation, message format,
hierarchy, and attribute storage.
"""

import pytest
from identity.domain.constants import DomainIdPrefix as IamPrefix
from seedwork.utils import generate_id

from edi.domain.constants import DomainIdPrefix as EdiPrefix
from edi.domain.exceptions import (
    DomainError,
    IdempotencyConflictError,
    InvalidCertificateActionError,
    MissingCertificateError,
    OrchestrationError,
    PartnerAlreadyExistsError,
    PartnerInUseError,
    PartnerNotFoundError,
    ResourceNotFoundError,
    TransactionNotFoundError,
    VaultError,
)


class TestExceptionHierarchy:
    def test_domain_error_is_base_exception(self):
        assert issubclass(DomainError, Exception)

    def test_partner_not_found_is_domain_error(self):
        assert issubclass(PartnerNotFoundError, DomainError)

    def test_partner_already_exists_is_domain_error(self):
        assert issubclass(PartnerAlreadyExistsError, DomainError)

    def test_partner_in_use_is_domain_error(self):
        assert issubclass(PartnerInUseError, DomainError)

    def test_invalid_cert_action_is_domain_error(self):
        assert issubclass(InvalidCertificateActionError, DomainError)

    def test_missing_certificate_is_domain_error(self):
        assert issubclass(MissingCertificateError, DomainError)

    def test_transaction_not_found_is_domain_error(self):
        assert issubclass(TransactionNotFoundError, DomainError)

    def test_idempotency_conflict_is_base_exception(self):
        assert issubclass(IdempotencyConflictError, Exception)

    def test_orchestration_error_is_base_exception(self):
        assert issubclass(OrchestrationError, Exception)

    def test_vault_error_is_base_exception(self):
        assert issubclass(VaultError, Exception)

    def test_resource_not_found_is_base_exception(self):
        assert issubclass(ResourceNotFoundError, Exception)


class TestPartnerNotFoundError:
    def test_stores_partner_id_attribute(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerNotFoundError(partner_id=p_id, tenant_id=t_id)
        assert err.partner_id == p_id

    def test_stores_tenant_id_attribute(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerNotFoundError(partner_id=p_id, tenant_id=t_id)
        assert err.tenant_id == t_id

    def test_message_contains_partner_and_tenant(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerNotFoundError(partner_id=p_id, tenant_id=t_id)
        assert p_id in str(err)
        assert t_id in str(err)

    def test_can_be_raised_and_caught(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        with pytest.raises(PartnerNotFoundError) as exc_info:
            raise PartnerNotFoundError(partner_id=p_id, tenant_id=t_id)
        assert exc_info.value.partner_id == p_id


class TestPartnerAlreadyExistsError:
    def test_stores_as2_id_and_tenant_id(self):
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerAlreadyExistsError(as2_id="AS2_ID_01", tenant_id=t_id)
        assert err.as2_id == "AS2_ID_01"
        assert err.tenant_id == t_id

    def test_message_contains_as2_id(self):
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerAlreadyExistsError(as2_id="MY_AS2", tenant_id=t_id)
        assert "MY_AS2" in str(err)


class TestPartnerInUseError:
    def test_stores_partner_id_and_tenant_id(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerInUseError(partner_id=p_id, tenant_id=t_id)
        assert err.partner_id == p_id
        assert err.tenant_id == t_id

    def test_message_contains_partner_id(self):
        p_id = generate_id(EdiPrefix.AS2_PARTNER)
        t_id = generate_id(IamPrefix.TENANT)
        err = PartnerInUseError(partner_id=p_id, tenant_id=t_id)
        assert p_id in str(err)


class TestInvalidCertificateActionError:
    def test_stores_action(self):
        err = InvalidCertificateActionError(action="delete")
        assert err.action == "delete"

    def test_message_contains_action_and_valid_options(self):
        err = InvalidCertificateActionError(action="delete")
        assert "delete" in str(err)
        assert "generate" in str(err)
        assert "upload" in str(err)


class TestTransactionNotFoundError:
    def test_stores_trace_id(self):
        t_id = generate_id("sys_trc")
        err = TransactionNotFoundError(trace_id=t_id)
        assert err.trace_id == t_id

    def test_message_contains_trace_id(self):
        t_id = generate_id("sys_trc")
        err = TransactionNotFoundError(trace_id=t_id)
        assert t_id in str(err)

    def test_can_be_raised_and_caught(self):
        t_id = generate_id("sys_trc")
        with pytest.raises(TransactionNotFoundError) as exc_info:
            raise TransactionNotFoundError(trace_id=t_id)
        assert exc_info.value.trace_id == t_id


class TestSimpleExceptions:
    def test_idempotency_conflict_is_raisable(self):
        with pytest.raises(IdempotencyConflictError):
            raise IdempotencyConflictError("key already used")

    def test_orchestration_error_is_raisable(self):
        with pytest.raises(OrchestrationError):
            raise OrchestrationError("provisioning failed")

    def test_vault_error_is_raisable(self):
        with pytest.raises(VaultError):
            raise VaultError("vault unreachable")

    def test_resource_not_found_is_raisable(self):
        with pytest.raises(ResourceNotFoundError):
            raise ResourceNotFoundError("resource missing")

    def test_missing_certificate_is_raisable(self):
        with pytest.raises(MissingCertificateError):
            raise MissingCertificateError("no cert found")
