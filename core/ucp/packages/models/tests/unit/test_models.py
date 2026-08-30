from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App, AppSubscription


def test_control_plane_outbox_instantiation():
    event = ControlPlaneOutbox(
        id="cp_ucp_ob_123",
        tenant_id="tenant-1",
        event_type="test_event",
        idempotency_key="key-1",
        payload={"key": "value"},
        status="PENDING",
    )
    assert event.id == "cp_ucp_ob_123"
    assert event.tenant_id == "tenant-1"
    assert event.event_type == "test_event"
    assert event.status == "PENDING"
    # Ensure body alias returns payload
    assert event.body == {"key": "value"}


def test_app_instantiation():
    app = App(
        slug="test-app",
        name="Test Application",
        description="A test app",
    )
    assert app.slug == "test-app"
    assert app.name == "Test Application"
    assert app.description == "A test app"
    assert hasattr(app, "created_at")


def test_app_subscription_instantiation():
    sub = AppSubscription(
        tenant_id="tenant-1",
        app_id="app-1",
        tier="premium",
        status="active",
    )
    assert sub.tenant_id == "tenant-1"
    assert sub.app_id == "app-1"
    assert sub.tier == "premium"


def test_database_shard_instantiation():
    shard = DatabaseShard(
        id="ucp_shard_1",
        name="primary_shard",
        dsn="postgresql://user:pass@localhost:5432/db",
    )
    assert shard.id == "ucp_shard_1"
    assert shard.name == "primary_shard"
    assert shard.dsn == "postgresql://user:pass@localhost:5432/db"


def test_shard_registry_instantiation():
    registry = ShardRegistry(
        tenant_id="tenant-1",
        app_id="app-1",
        shard_id="ucp_shard_1",
    )
    assert registry.tenant_id == "tenant-1"
    assert registry.app_id == "app-1"
    assert registry.shard_id == "ucp_shard_1"
