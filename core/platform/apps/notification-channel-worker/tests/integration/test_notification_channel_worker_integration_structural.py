import pytest

pytestmark = pytest.mark.integration

from notification_channel_worker.bootstrap.container import WorkerContainer
from notification_channel_worker.main import main


def test_structural():
    container = WorkerContainer()
    assert container is not None
    assert callable(main)
