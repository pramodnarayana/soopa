"""Deprecated: child_workflow_steps.py has been removed in favor of queue-backed tasks.

ChildWorkflowFanOutStepHandler violated the Single Responsibility Principle (SRP)
and granularity of Stitches. Fanout is handled via queue-backed task dispatching.
"""

from __future__ import annotations

__all__: list[str] = []
