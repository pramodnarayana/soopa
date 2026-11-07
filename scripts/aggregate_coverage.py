#!/usr/bin/env python3
import argparse
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


def stage_package_artifacts(
    pkg_dir: str,
    artifacts_dir: str,
    repo_root: str = ".",
) -> list[str]:
    rel_pkg_dir = os.path.relpath(pkg_dir, repo_root)
    if not os.path.isdir(artifacts_dir):
        return []

    staged_paths: list[str] = []
    shard_index = 0
    for entry in sorted(os.listdir(artifacts_dir)):
        subdir_path = os.path.join(artifacts_dir, entry)
        if not os.path.isdir(subdir_path):
            continue
        if entry.startswith("coverage-unit"):
            candidate_filenames = (".coverage.unit",)
        elif entry.startswith("coverage-integration"):
            candidate_filenames = (".coverage.integration",)
        else:
            continue

        for filename in candidate_filenames:
            src_file = os.path.join(subdir_path, rel_pkg_dir, filename)
            if os.path.isfile(src_file):
                shard_index += 1
                dest_file = os.path.join(pkg_dir, f".coverage.shard_{shard_index}")
                shutil.copy2(src_file, dest_file)
                staged_paths.append(dest_file)

    return staged_paths


def has_coverage_script(pkg_json: str) -> bool:
    if "node_modules" in pkg_json:
        return False

    with open(pkg_json, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return False

    scripts = data.get("scripts") if isinstance(data, dict) else None
    return isinstance(scripts, dict) and "cov" in scripts


def prepare_coverage_inputs(
    pkg_dir: str,
    artifacts_dir: str | None,
    repo_root: str = ".",
) -> bool:
    for entry in os.listdir(pkg_dir):
        if entry == ".coverage" or entry.startswith((".coverage.shard_", ".coverage.local_")):
            os.remove(os.path.join(pkg_dir, entry))

    staged_paths: list[str] = []
    if artifacts_dir is not None:
        staged_paths = stage_package_artifacts(pkg_dir, artifacts_dir, repo_root=repo_root)

    unit_cov = os.path.join(pkg_dir, ".coverage.unit")
    int_cov = os.path.join(pkg_dir, ".coverage.integration")

    has_local_inputs = os.path.exists(unit_cov) or os.path.exists(int_cov)
    if not staged_paths and not has_local_inputs:
        return False

    if os.path.exists(unit_cov):
        os.rename(unit_cov, os.path.join(pkg_dir, ".coverage.local_unit"))
    if os.path.exists(int_cov):
        os.rename(int_cov, os.path.join(pkg_dir, ".coverage.local_integration"))

    return True


def process_package(
    pkg_json: str,
    uv_path: str,
    rcfile_path: str,
    artifacts_dir: str | None = None,
) -> bool:
    if not has_coverage_script(pkg_json):
        return True

    pkg_dir = os.path.dirname(pkg_json)
    if not prepare_coverage_inputs(pkg_dir, artifacts_dir):
        return True

    sys.stdout.write("\n==================================================\n")
    sys.stdout.write(f"Aggregating coverage for {pkg_dir}\n")
    sys.stdout.write("==================================================\n")

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine and validate per-package unit and integration coverage."
    )
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Optional directory containing downloaded coverage-unit and coverage-integration artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uv_path = get_uv_path()
    rcfile_path = os.path.abspath("pyproject.toml")
    artifacts_dir = os.path.abspath(args.artifacts_dir) if args.artifacts_dir else None
    failed = False

    for root, dirs, files in os.walk(".", topdown=True):
        dirs[:] = [
            d for d in dirs if not d.startswith(".") and d not in ("node_modules", "dist", "build")
        ]
        if "package.json" in files:
            pkg_json = os.path.join(root, "package.json")
            success = process_package(pkg_json, uv_path, rcfile_path, artifacts_dir)
            if not success:
                failed = True

    if failed:
        sys.exit(1)
    else:
        sys.stdout.write("\n✅ All packages passed coverage threshold!\n")


if __name__ == "__main__":
    main()
