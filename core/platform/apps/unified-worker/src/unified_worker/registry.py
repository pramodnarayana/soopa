import importlib

from seedwork.infra.worker import LaunchableWorker


def get_worker_instance(worker_name: str) -> LaunchableWorker:
    """
    Dynamically loads and instantiates a LaunchableWorker by its canonical name.
    """
    registry = {
        "identity-worker": "identity_worker.main.IdentityWorkerModule",
        "identity-jobs-worker": "identity_jobs_worker.main.IdentityJobsWorkerModule",
        "notification-worker": "notification_worker.main.NotificationWorkerModule",
        "notification-jobs-worker": "notification_jobs_worker.main.NotificationJobsWorkerModule",
        "notification-channel-worker": "notification_channel_worker.main.NotificationChannelWorkerModule",
        "ucp-worker": "ucp_worker.main.UcpWorkerModule",
        "ucp-jobs-worker": "ucp_jobs_worker.main.UcpJobsWorkerModule",
        "scheduler-worker": "scheduler_worker.main.SchedulerWorkerModule",
        "edi-orchestrator-worker": "worker.main.EdiOrchestratorWorkerModule",
        "edi-delivery-worker": "edi_delivery_worker.main.EdiDeliveryWorkerModule",
        "edi-compute-worker": "compute_worker.main.EdiComputeWorkerModule",
        "edi-config-sync-worker": "config_sync_worker.provision.main.EdiConfigSyncWorkerModule",
        "edi-cp-jobs-worker": "edi_cp_jobs_worker.main.EdiCpJobsWorkerModule",
        "edi-dp-jobs-worker": "edi_dp_jobs_worker.main.EdiDpJobsWorkerModule",
    }

    if worker_name not in registry:
        raise ValueError(f"Unknown worker module: {worker_name}")

    module_path, class_name = registry[worker_name].rsplit(".", 1)

    try:
        module = importlib.import_module(module_path)
        worker_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise RuntimeError(f"Failed to load worker class {registry[worker_name]}: {e}") from e

    # We assume the module class has a zero-argument constructor that satisfies LaunchableWorker
    return worker_class()
