from edi.config.settings import AppSettings, AwsSettings, SqsSettings

from edi_background_worker.main import _create_scheduled_job_consumers


def test_scheduled_job_consumers_use_configured_region_and_queue_urls() -> None:
    settings = AppSettings.model_construct(
        aws=AwsSettings(
            region="eu-west-2",
            endpoint_url="https://sqs.eu-west-2.amazonaws.com",
        ),
        sqs=SqsSettings.model_construct(
            data_plane_jobs_queue_url=(
                "https://sqs.eu-west-2.amazonaws.com/123456789/edi-data-plane-jobs.fifo"
            ),
            control_plane_jobs_queue_url=(
                "https://sqs.eu-west-2.amazonaws.com/123456789/edi-control-plane-jobs.fifo"
            ),
        ),
    )

    data_plane_consumer, control_plane_consumer = _create_scheduled_job_consumers(settings)

    assert data_plane_consumer.region_name == "eu-west-2"
    assert control_plane_consumer.region_name == "eu-west-2"
    assert data_plane_consumer.queue_url == settings.sqs.data_plane_jobs_queue_url
    assert control_plane_consumer.queue_url == settings.sqs.control_plane_jobs_queue_url
