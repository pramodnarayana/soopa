"""Outbound ports for ABAC/Casbin policy rules and optional tenant-filtered Casbin evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from identity.domain.dtos import AuthzDecision, AuthzRequest, PolicyRuleDTO


class PolicyRuleRepositoryPort(Protocol):
    """Persists and queries custom tenant ABAC / Casbin policy rules."""

    async def list_active_rules(self, *, tenant_id: str) -> tuple[PolicyRuleDTO, ...]: ...

    async def save_rule(self, rule: PolicyRuleDTO) -> PolicyRuleDTO: ...

    async def delete_rule(self, *, tenant_id: str, rule_id: str) -> bool: ...


class CasbinRuleEvaluatorPort(Protocol):
    """Optional tenant-filtered local Casbin evaluator for custom enterprise PERM policies."""

    def evaluate_casbin_rules(
        self,
        *,
        rules: Sequence[PolicyRuleDTO],
        request: AuthzRequest,
        effective_role_ids: frozenset[str],
    ) -> AuthzDecision | None: ...


__all__ = ["CasbinRuleEvaluatorPort", "PolicyRuleRepositoryPort"]
