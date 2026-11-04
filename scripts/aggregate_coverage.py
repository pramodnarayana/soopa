#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys


def get_uv_path() -> str:
    uv_path = shutil.which("uv")
    if not uv_path:
        sys.stdout.write("❌ Error: 'uv' executable not found in PATH.\n")
        sys.exit(1)
    return uv_path


def process_package(pkg_json: str, uv_path: str, rcfile_path: str) -> bool:
    if "node_modules" in pkg_json:
        return True

    pkg_dir = os.path.dirname(pkg_json)

    with open(pkg_json) as f:
        try:
            data = json.load(f)
            if "scripts" not in data or "cov" not in data["scripts"]:
                return True
        except json.JSONDecodeError:
            return True

    unit_cov = os.path.join(pkg_dir, ".coverage.unit")
    int_cov = os.path.join(pkg_dir, ".coverage.integration")

    if not (os.path.exists(unit_cov) or os.path.exists(int_cov)):
        return True

    sys.stdout.write("\n==================================================\n")
    sys.stdout.write(f"Aggregating coverage for {pkg_dir}\n")
    sys.stdout.write("==================================================\n")

    if os.path.exists(unit_cov):
        os.rename(unit_cov, os.path.join(pkg_dir, ".coverage.1"))
    if os.path.exists(int_cov):
        os.rename(int_cov, os.path.join(pkg_dir, ".coverage.2"))

    try:
        subprocess.run(  # noqa: S603 - Safe uv path resolved via shutil.which
            [uv_path, "run", "coverage", "combine", f"--rcfile={rcfile_path}"],
            cwd=pkg_dir,
            check=True,
        )
        result = subprocess.run(  # noqa: S603 - Safe uv path resolved via shutil.which
            [
                uv_path,
                "run",
                "coverage",
                "report",
                f"--rcfile={rcfile_path}",
                "--fail-under=80",
            ],
            cwd=pkg_dir,
            check=False,
        )

        if result.returncode != 0:
            sys.stdout.write(f"❌ Coverage threshold failed for {pkg_dir}\n")
            return False

        sys.stdout.write(f"✅ Coverage passed for {pkg_dir}\n")
        return True

    except subprocess.CalledProcessError as e:
        sys.stdout.write(f"❌ Error combining coverage in {pkg_dir}: {e}\n")
        return False
    except OSError as e:
        sys.stdout.write(f"❌ OS Error processing {pkg_dir}: {e}\n")
        return False


def main() -> None:
    uv_path = get_uv_path()
    rcfile_path = os.path.abspath("pyproject.toml")
    failed = False

    for root, dirs, files in os.walk(".", topdown=True):
        dirs[:] = [
            d for d in dirs if not d.startswith(".") and d not in ("node_modules", "dist", "build")
        ]
        if "package.json" in files:
            pkg_json = os.path.join(root, "package.json")
            success = process_package(pkg_json, uv_path, rcfile_path)
            if not success:
                failed = True

    if failed:
        sys.exit(1)
    else:
        sys.stdout.write("\n✅ All packages passed coverage threshold!\n")


if __name__ == "__main__":
    main()
