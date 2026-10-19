"""Paramiko host-key policies for SFTP connections."""

from __future__ import annotations

import paramiko


class DiagnosticHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Silently accepts any host key during diagnostic connectivity test pings.

    This policy is strictly intended for diagnostic credential checks and ping tests.
    Production data transfers must use setup_host_key with RejectPolicy.
    """

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        pass
