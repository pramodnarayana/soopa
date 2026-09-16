import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


def sync_deps(check_only: bool = False):  # noqa: C901
    root = Path(".")
    pyprojects = list(root.rglob("pyproject.toml"))

    # Pass 1: Map all Python project names to their package.json npm names
    py_to_npm = {}
    for pyproject in pyprojects:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                py_name = data["project"]["name"]
                pkg_json = pyproject.parent / "package.json"
                if pkg_json.exists():
                    with open(pkg_json) as pj:
                        pkg_data = json.load(pj)
                        py_to_npm[py_name] = pkg_data.get("name")

    # Pass 2: Sync dependencies
    out_of_sync_files = []

    for pyproject in pyprojects:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        pkg_json = pyproject.parent / "package.json"
        if not pkg_json.exists():
            continue

        uv_sources = data.get("tool", {}).get("uv", {}).get("sources", {})
        if not uv_sources:
            continue

        actual_deps = []
        if "project" in data and "dependencies" in data["project"]:
            for d in data["project"]["dependencies"]:
                # extract just the package name (e.g. 'fastapi' from 'fastapi>=0.141.1')
                name = re.match(r"^([a-zA-Z0-9_\-]+)", d).group(1)
                actual_deps.append(name.replace("-", "_"))

        if "dependency-groups" in data:
            for _group, deps in data["dependency-groups"].items():
                for d in deps:
                    match = re.match(r"^([a-zA-Z0-9_\-]+)", d)
                    if match:
                        actual_deps.append(match.group(1).replace("-", "_"))

        deps_to_add = {}
        for dep_name, source in uv_sources.items():
            if (
                dep_name.replace("-", "_") in actual_deps
                and isinstance(source, dict)
                and source.get("workspace") is True
            ):
                npm_name = py_to_npm.get(dep_name)
                if npm_name:
                    deps_to_add[npm_name] = "workspace:*"

        if deps_to_add:
            with open(pkg_json) as pj:
                pkg_data = json.load(pj)

            if "devDependencies" not in pkg_data:
                pkg_data["devDependencies"] = {}

            updated = False
            for dep, val in deps_to_add.items():
                if pkg_data["devDependencies"].get(dep) != val:
                    pkg_data["devDependencies"][dep] = val
                    updated = True

            if updated:
                if check_only:
                    out_of_sync_files.append(str(pkg_json))
                else:
                    with open(pkg_json, "w") as pj:
                        json.dump(pkg_data, pj, indent=2)
                        pj.write("\n")
                    print(f"Updated {pkg_json}")  # noqa: T201

    if check_only and out_of_sync_files:
        print(  # noqa: T201
            "ERROR: The following package.json files are out of sync with pyproject.toml workspaces:"
        )
        for f in out_of_sync_files:
            print(f" - {f}")  # noqa: T201
        print("\nRun 'pnpm run syncpack:python' to fix this automatically.")  # noqa: T201
        sys.exit(1)
    elif check_only:
        print("All Python workspace dependencies are correctly mirrored in package.json files.")  # noqa: T201
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if out of sync")
    args = parser.parse_args()
    sync_deps(check_only=args.check)
