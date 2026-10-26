"""Default Hatchet-inspired StepErrorPolicyPort implementation."""

from __future__ import annotations

from datetime import timedelta

from orchestration.domain.constants import EffectPolicy, ErrorDecisionKind, StepFailureCode
from orchestration.domain.definition import NodeDefinition
from orchestration.domain.failures import (
    ErrorPolicyDecision,
    RetryableFailure,
    StepFailure,
    TerminalFailure,
)
from orchestration.domain.run import StepRun
from orchestration.ports.inbound.step_handler_port import StepErrorPolicyPort


class DefaultStepErrorPolicy(StepErrorPolicyPort):
    """Evaluates step failures against NodeDefinition retry policies, effect policies, and Hatchet 3-counter rules:
    1. TerminalFailure or non-retryable code -> FAIL_TERMINAL.
    2. Ambiguous crash/lease expiry on OPERATOR_GATED_EFFECT -> FAIL_AMBIGUOUS_OPERATOR_GATE (never auto-retry!).
    3. RetryableFailure with RATE_LIMITED -> PARK_FOR_RATE_LIMIT (does NOT burn app_retry_count).
    4. Worker crash / lease expiry (`is_app_error=False`) -> RETRY up to `max_internal_retries` without burning `app_retry_count`.
    5. Application RetryableFailure (`is_app_error=True`) -> RETRY with exponential backoff if `app_retry_count + 1 < max_attempts`, else FAIL_TERMINAL.
    """

    def decide(
        self,
        *,
        failure: StepFailure,
        step_run: StepRun,
        node_definition: NodeDefinition,
    ) -> ErrorPolicyDecision:
        retry_policy = node_definition.retry_policy

        if isinstance(failure, TerminalFailure):
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.FAIL_TERMINAL,
                failure_code=failure.code,
                failure_detail=failure.detail,
            )

        assert isinstance(failure, RetryableFailure)

        if failure.code in retry_policy.non_retryable_codes:
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.FAIL_TERMINAL,
                failure_code=failure.code,
                failure_detail=failure.detail,
            )

        # Ambiguous crash/lease expiry on an OPERATOR_GATED_EFFECT step must NEVER auto-retry
        if (
            not failure.is_app_error
            and node_definition.effect_policy == EffectPolicy.OPERATOR_GATED_EFFECT
        ):
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.FAIL_AMBIGUOUS_OPERATOR_GATE,
                failure_code=StepFailureCode.AMBIGUOUS_EFFECT,
                failure_detail=(
                    f"Ambiguous crash on OPERATOR_GATED_EFFECT step '{step_run.node_key}': "
                    f"{failure.detail}. Operator reconciliation required."
                ),
            )

        # Upstream 429 / RATE_LIMITED parks in workflow_paused_queue_items without burning app_retry_count
        if failure.code == StepFailureCode.RATE_LIMITED:
            park_delay = failure.retry_after or timedelta(seconds=30)
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.PARK_FOR_RATE_LIMIT,
                delay=park_delay,
                failure_code=failure.code,
                failure_detail=failure.detail,
            )

        # Internal / worker crash retry budget (`internal_retry_count`)
        if not failure.is_app_error:
            if step_run.internal_retry_count < retry_policy.max_internal_retries:
                return ErrorPolicyDecision(
                    kind=ErrorDecisionKind.RETRY,
                    delay=retry_policy.initial_backoff,
                    failure_code=failure.code,
                    failure_detail=failure.detail,
                )
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.FAIL_TERMINAL,
                failure_code=failure.code,
                failure_detail=f"Exhausted max_internal_retries ({retry_policy.max_internal_retries}): {failure.detail}",
            )

        # Application retry budget (`app_retry_count + 1 < max_attempts`)
        next_attempt_number = step_run.app_retry_count + 1
        if next_attempt_number < retry_policy.max_attempts:
            backoff = (
                failure.retry_after
                if failure.retry_after is not None
                else retry_policy.compute_backoff(next_attempt_number)
            )
            return ErrorPolicyDecision(
                kind=ErrorDecisionKind.RETRY,
                delay=backoff,
                failure_code=failure.code,
                failure_detail=failure.detail,
            )

        return ErrorPolicyDecision(
            kind=ErrorDecisionKind.FAIL_TERMINAL,
            failure_code=failure.code,
            failure_detail=f"Exhausted max_attempts ({retry_policy.max_attempts}): {failure.detail}",
        )


__all__ = ["DefaultStepErrorPolicy"]
