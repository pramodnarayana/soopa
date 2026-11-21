from notification_channel_worker.bootstrap.container import WorkerContainer


def test_structural() -> None:
    container = WorkerContainer()
    assert container.email_channel_consumer is not None
    assert container.email_dispatcher is not None
