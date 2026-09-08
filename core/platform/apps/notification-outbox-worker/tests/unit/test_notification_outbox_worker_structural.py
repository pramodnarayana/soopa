from notification_outbox_worker.bootstrap.container import WorkerContainer


def test_structural():
    container = WorkerContainer()
    assert container.outbox_listener is not None
