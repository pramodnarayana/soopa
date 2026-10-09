"""
infra_seedwork.env
==================
Utilities for converting topology-driven queue env vars into ECS task
definition environment format.

Centralised here so compute stacks never duplicate this transformation logic.
"""

EDI_ENVIRONMENT_PRODUCTION = "P"
EDI_ENVIRONMENT_TEST = "T"
PRODUCTION_STACK_NAME = "production"


def edi_environment_flag(stack_name: str) -> str:
    """
    Maps a Pulumi stack name to the ``EDI_ENVIRONMENT`` flag required by the EDI
    worker settings (``P`` = Production, ``T`` = Test). Every non-production
    stack (e.g. staging) runs in Test mode.
    """
    if stack_name == PRODUCTION_STACK_NAME:
        return EDI_ENVIRONMENT_PRODUCTION
    return EDI_ENVIRONMENT_TEST


def queue_env_vars_to_ecs_format(
    queue_env_vars: dict[str, str],
    static_vars: dict[str, str],
) -> list[dict[str, str]]:
    """
    Merges topology-driven queue/topic env vars with static platform env vars
    and converts the result into the ECS task definition ``environment`` format:
    ``[{"name": "KEY", "value": "VALUE"}, ...]``.

    Args:
        queue_env_vars: Resolved map from topology (e.g. SQS_* and SNS_* URLs).
                        Comes from ``TopologyOutput.queue_env_vars`` after Pulumi
                        resolution inside an ``.apply()`` callback.
        static_vars:    Non-topology env vars that are statically known at plan
                        time (e.g. ENVIRONMENT, PUBLIC_BASE_URL).

    Returns:
        ECS-compatible list of ``{"name": ..., "value": ...}`` dicts.
    """
    entries: list[dict[str, str]] = [{"name": k, "value": v} for k, v in static_vars.items()]
    for env_var_name, url in queue_env_vars.items():
        entries.append({"name": env_var_name, "value": url})
    return entries
