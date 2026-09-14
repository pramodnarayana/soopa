from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Walk up the directory tree to find the repository root.

    The root is identified by the presence of a ``.git`` directory, which is
    always present in any properly initialised git repository.

    This function is intentionally used instead of a hardcoded ``parents[N]``
    magic number, which would silently break if any directory in the hierarchy
    were renamed or reorganised.

    Args:
        start: The starting path (typically ``Path(__file__).resolve()``).

    Returns:
        The absolute path to the repository root directory.

    Raises:
        RuntimeError: If no ``.git`` directory can be found by traversing all
            ancestors of ``start``. This is an unrecoverable startup error.
    """
    for candidate in [start, *start.parents]:
        if (candidate / ".git").is_dir():
            return candidate
    raise RuntimeError(
        f"Could not locate repository root starting from '{start}'. "
        "Ensure the project is initialised as a git repository with a "
        ".git directory at the root."
    )
