from notification_email_worker.bootstrap.container import WorkerContainer
from notification_email_worker.main import main


def test_structural():
    container = WorkerContainer()
    assert container is not None
    assert callable(main)
