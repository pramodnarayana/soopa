import os
import subprocess

env = os.environ.copy()
if "PULUMI_CONFIG_PASSPHRASE" not in env:
    raise RuntimeError("PULUMI_CONFIG_PASSPHRASE must be set in the environment")
subprocess.run(["pulumi", "preview", "-s", "staging"], env=env, check=True)  # noqa: S607 - Pulumi CLI is dynamically invoked in infrastructure automation
