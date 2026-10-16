"""Pure unit tests for EDI migration runner path resolution (Zero Mocks)."""

import pytest

from edi.adapters.outbound.database.run_migrations import (
    find_edi_ini_path,
    find_edi_script_location,
)


def test_find_edi_ini_path_locates_global_and_tenant_ini():
    """Verify that global and tenant Alembic configuration files are reliably located."""
    global_ini = find_edi_ini_path("alembic.global.ini")
    assert global_ini.exists()
    assert global_ini.name == "alembic.global.ini"

    tenant_ini = find_edi_ini_path("alembic.tenant.ini")
    assert tenant_ini.exists()
    assert tenant_ini.name == "alembic.tenant.ini"


def test_find_edi_ini_path_raises_on_missing_file():
    """Verify that a clear FileNotFoundError is raised when an ini file cannot be found."""
    with pytest.raises(FileNotFoundError, match=r"Could not locate nonexistent\.ini"):
        find_edi_ini_path("nonexistent.ini")


def test_find_edi_script_location_locates_migration_directories():
    """Verify that global and tenant migration script locations exist."""
    global_loc = find_edi_script_location("global")
    assert global_loc.exists()
    assert global_loc.name == "global"

    tenant_loc = find_edi_script_location("tenant")
    assert tenant_loc.exists()
    assert tenant_loc.name == "tenant"


def test_find_edi_script_location_raises_on_unknown_domain():
    """Verify that a clear FileNotFoundError is raised for unknown migration domains."""
    with pytest.raises(
        FileNotFoundError, match=r"Could not locate migration scripts for 'unknown'"
    ):
        find_edi_script_location("unknown")
