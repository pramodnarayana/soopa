"""Pure, domain-agnostic Pulumi StackReference helpers for multi-layer PR previews."""

from __future__ import annotations

import pulumi


def resolve_stack_output_value(
    value: object,
    *,
    output_name: str,
    preview_placeholder: str,
    is_dry_run: bool,
) -> str:
    """Resolve a required upstream stack output, allowing a placeholder ONLY during preview."""
    if isinstance(value, str) and value.strip():
        return value
    if is_dry_run:
        return preview_placeholder
    raise KeyError(
        f"Required stack output '{output_name}' is missing from upstream StackReference "
        "(deploy the upstream infrastructure stack first)."
    )


def require_stack_output_or_preview_placeholder(
    stack_ref: pulumi.StackReference,
    output_name: str,
    *,
    preview_placeholder: str,
) -> pulumi.Output[str]:
    """Read a required StackReference output while staying preview-safe during same-PR rollouts.

    During `pulumi preview` (`pulumi.runtime.is_dry_run() == True`), returns `preview_placeholder`
    when an upstream stack output introduced in the same PR has not been deployed yet.
    During live deployments (`pulumi up`, `is_dry_run() == False`), fails fast with `KeyError`
    if the upstream stack has not exported `output_name`.
    """
    return stack_ref.get_output(output_name).apply(
        lambda val: resolve_stack_output_value(
            val,
            output_name=output_name,
            preview_placeholder=preview_placeholder,
            is_dry_run=pulumi.runtime.is_dry_run(),
        )
    )


__all__ = [
    "require_stack_output_or_preview_placeholder",
    "resolve_stack_output_value",
]
