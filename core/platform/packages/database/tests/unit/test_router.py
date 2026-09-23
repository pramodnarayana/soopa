from database.router import DatabaseRouter


def test_resolve_dsn_applies_overrides() -> None:
    """Test that DatabaseRouter properly resolves DSN overrides regardless of case."""
    # 1. Arrange: Simulate Pydantic injecting environment variables
    # Pydantic often converts config values in unexpected ways depending on case sensitivity configs.
    # We'll simulate a mix of lowercase, uppercase, and mixed-case keys.
    overrides = {
        "EDI_SHARD_1": "postgresql+asyncpg://edi@localhost/override_1",
        "edi_shard_2": "postgresql+asyncpg://edi@localhost/override_2",
        "Edi_Shard_3": "postgresql+asyncpg://edi@localhost/override_3",
    }
    router = DatabaseRouter(
        global_db_url="postgresql+asyncpg://global@localhost/global",
        shard_overrides=overrides,
    )

    # 2. Act & Assert: Verify it resolves correctly against exactly matching keys,
    # completely different casing, and missing keys.

    # 2.1 Exact Match (but original was uppercase)
    assert (
        router._resolve_dsn("default_dsn", "EDI_SHARD_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.2 Lowercase query for an uppercase original key
    assert (
        router._resolve_dsn("default_dsn", "edi_shard_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.3 Uppercase query for a lowercase original key
    assert (
        router._resolve_dsn("default_dsn", "EDI_SHARD_2")
        == "postgresql+asyncpg://edi@localhost/override_2"
    )

    # 2.4 Mixed case query for a mixed case original key
    assert (
        router._resolve_dsn("default_dsn", "eDi_ShArD_3")
        == "postgresql+asyncpg://edi@localhost/override_3"
    )

    # 2.5 Fallback test (multiple keys)
    assert (
        router._resolve_dsn("default_dsn", "non_existent", "EDI_SHARD_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.6 Missing key completely returns the default DSN
    assert router._resolve_dsn("default_dsn", "MISSING_SHARD") == "default_dsn"
