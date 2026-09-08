from notification_email_worker.bootstrap.container import WorkerContainer


def test_structural():
    container = WorkerContainer()
    assert container.email_delivery_consumer is not None
    assert container.email_dispatcher is not None
