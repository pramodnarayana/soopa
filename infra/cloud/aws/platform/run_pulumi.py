import os
import subprocess

env = os.environ.copy()
env["PULUMI_CONFIG_PASSPHRASE"] = "local"  # noqa: S105 - Ephemeral state passphrase for local staging automation
subprocess.run(["pulumi", "preview", "-s", "staging"], env=env)  # noqa: S607 - Pulumi CLI is globally installed via system package manager
