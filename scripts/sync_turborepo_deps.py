import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


def sync_deps(check_only: bool = False):  # noqa: C901 - Multi-pass AST script complexity
    root = Path(".")
    pyprojects = [
        p
        for p in root.rglob("pyproject.toml")
        if not any(part.startswith(".") or part in ("node_modules", ".venv") for part in p.parts)
    ]

    # Pass 1: Map all Python project names to their package.json npm names
    py_to_npm: dict[str, str] = {}
    for pyproject in pyprojects:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
            if "project" in data and "name" in data["project"]:
                py_name = data["project"]["name"]
                pkg_json = pyproject.parent / "package.json"
                if pkg_json.exists():
                    with open(pkg_json) as pj:
                        pkg_data = json.load(pj)
                        npm_name = pkg_data.get("name")
                        if npm_name:
                            py_to_npm[py_name] = npm_name
                            py_to_npm[py_name.replace("-", "_")] = npm_name
                            py_to_npm[py_name.replace("_", "-")] = npm_name

    # Pass 2: Sync dependencies, prune stale mappings, detect phantom sources & validate invariants
    out_of_sync_files: list[tuple[str, str]] = []
    stale_dep_files: list[tuple[str, str]] = []
    phantom_source_files: list[tuple[str, str]] = []
    invalid_script_files: list[tuple[str, str, str]] = []

    known_npm_packages = set(py_to_npm.values())

    for pyproject in pyprojects:
        is_subpackage = pyproject.parent.resolve() != root.resolve()
        if not is_subpackage:
            continue

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

        pkg_json = pyproject.parent / "package.json"
        if not pkg_json.exists():
            continue

        # Invariant check: Subpackages containing pyproject.toml must invoke python tools via 'uv run'
        if is_subpackage:
            with open(pkg_json) as pj:
                pkg_data = json.load(pj)
            scripts = pkg_data.get("scripts", {})
            for name in ("lint", "test", "typecheck"):
                cmd = scripts.get(name, "")
                if cmd and "uv run" not in cmd and not cmd.startswith("echo"):
                    invalid_script_files.append((str(pkg_json), name, cmd))

        uv_sources = data.get("tool", {}).get("uv", {}).get("sources", {})

        actual_deps: list[str] = []
        if "project" in data and "dependencies" in data["project"]:
            for d in data["project"]["dependencies"]:
                match = re.match(r"^([a-zA-Z0-9_\-]+)", d)
                if match:
                    actual_deps.append(match.group(1).replace("-", "_"))

        if "project" in data and "optional-dependencies" in data["project"]:
            for _extra, deps in data["project"]["optional-dependencies"].items():
                for d in deps:
                    match = re.match(r"^([a-zA-Z0-9_\-]+)", d)
                    if match:
                        actual_deps.append(match.group(1).replace("-", "_"))

        if "dependency-groups" in data:
            for _group, deps in data["dependency-groups"].items():
                for d in deps:
                    match = re.match(r"^([a-zA-Z0-9_\-]+)", d)
                    if match:
                        actual_deps.append(match.group(1).replace("-", "_"))

        # Detect phantom workspace sources in subpackage pyproject.toml
        if is_subpackage and uv_sources:
            phantoms_in_file: list[str] = []
            for dep_name, source in uv_sources.items():
                if isinstance(source, dict) and source.get("workspace") is True:
                    normalized = dep_name.replace("-", "_")
                    if normalized not in actual_deps:
                        phantoms_in_file.append(dep_name)
                        phantom_source_files.append((str(pyproject), dep_name))

            # Auto-prune phantom sources in fix mode
            if phantoms_in_file and not check_only:
                content = pyproject.read_text()
                lines = content.splitlines(keepends=True)
                new_lines = []
                for line in lines:
                    stripped = line.strip()
                    should_remove = False
                    for p in phantoms_in_file:
                        if re.match(
                            rf"^{re.escape(p)}\s*=\s*\{{.*workspace\s*=\s*true.*\}}", stripped
                        ):
                            should_remove = True
                            break
                    if not should_remove:
                        new_lines.append(line)
                pyproject.write_text("".join(new_lines))
                print(f"Pruned phantom workspace sources {phantoms_in_file} from {pyproject}")  # noqa: T201 - CLI output for script progress

        with open(pkg_json) as pj:
            pkg_data = json.load(pj)

        deps_to_add: dict[str, str] = {}
        for dep_name, source in uv_sources.items():
            if (
                dep_name.replace("-", "_") in actual_deps
                and isinstance(source, dict)
                and source.get("workspace") is True
            ):
                npm_name = py_to_npm.get(dep_name) or py_to_npm.get(dep_name.replace("-", "_"))
                if npm_name:
                    deps_to_add[npm_name] = "workspace:*"

        if "devDependencies" not in pkg_data:
            pkg_data["devDependencies"] = {}

        updated = False
        # 1. Add/update required dependencies
        for dep, val in deps_to_add.items():
            if pkg_data["devDependencies"].get(dep) != val:
                pkg_data["devDependencies"][dep] = val
                updated = True
                if check_only:
                    out_of_sync_files.append((str(pkg_json), f"missing: {dep}"))

        # 2. Prune stale @soopa/* dependencies no longer declared in pyproject.toml
        stale_deps = [
            k
            for k in pkg_data["devDependencies"]
            if k.startswith("@soopa/") and k in known_npm_packages and k not in deps_to_add
        ]
        for dep in stale_deps:
            if check_only:
                stale_dep_files.append((str(pkg_json), f"stale: {dep}"))
            else:
                del pkg_data["devDependencies"][dep]
                updated = True

        if updated and not check_only:
            with open(pkg_json, "w") as pj:
                json.dump(pkg_data, pj, indent=2)
                pj.write("\n")
            print(f"Updated {pkg_json}")  # noqa: T201 - CLI output for script progress

    if check_only:
        has_errors = False
        if invalid_script_files:
            has_errors = True
            print(  # noqa: T201 - CLI error reporting
                "ERROR: The following package.json scripts must execute Python tools via 'uv run':"
            )
            for path, script_name, cmd in invalid_script_files:
                print(f' - {path} -> "{script_name}": "{cmd}"')  # noqa: T201 - CLI error reporting

        if phantom_source_files:
            has_errors = True
            print(  # noqa: T201 - CLI error reporting
                "\nERROR: The following pyproject.toml files define phantom [tool.uv.sources] not in dependencies:"
            )
            for path, dep_name in phantom_source_files:
                print(f" - {path} -> phantom source: {dep_name}")  # noqa: T201 - CLI error reporting

        if out_of_sync_files:
            has_errors = True
            print(  # noqa: T201 - CLI error reporting
                "\nERROR: The following package.json files are missing required workspace dependencies:"
            )
            for path, reason in out_of_sync_files:
                print(f" - {path} ({reason})")  # noqa: T201 - CLI error reporting

        if stale_dep_files:
            has_errors = True
            print(  # noqa: T201 - CLI error reporting
                "\nERROR: The following package.json files have stale/unused workspace dependencies:"
            )
            for path, reason in stale_dep_files:
                print(f" - {path} ({reason})")  # noqa: T201 - CLI error reporting

        if has_errors:
            print(  # noqa: T201 - CLI error reporting
                "\nRun 'pnpm run syncpack:python' to automatically fix and prune all dependencies."
            )
            sys.exit(1)

        print("All Python workspace dependencies, sources, and script invariants are valid.")  # noqa: T201 - CLI status reporting
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if out of sync")
    args = parser.parse_args()
    sync_deps(check_only=args.check)
