from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func

from app.config import get_settings
from app.documents.ocr_runtime import configured_ocr_adapter
from app.observability import configure_error_tracking, configure_json_logging
from app.workers.delta import compute_opportunity_delta, reconcile_pending_deltas
from app.workers.eligibility import evaluate_company_opportunity, reconcile_eligibility_results
from app.workers.extraction import extract_version, reconcile_pending_extractions
from app.workers.jobs import (
    WORKER_QUEUE,
    ingest_record,
    poll_configured_sources,
    poll_source,
    reconcile_failed_jobs,
    reconcile_pending_documents,
    reconcile_pending_normalizations,
)
from app.workers.lifecycle import link_opportunity, reconcile_lifecycle_links
from app.workers.notifications import (
    deliver_notification,
    dispatch_pending_notifications,
    reconcile_notifications,
)
from app.workers.ranking import rank_company_opportunity, reconcile_ranking_results


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_json_logging()
    configure_error_tracking(settings)
    ctx["ocr_adapter"] = await configured_ocr_adapter(settings)


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    health_check_interval = 30
    functions = [
        poll_source,
        ingest_record,
        reconcile_failed_jobs,
        reconcile_pending_normalizations,
        reconcile_pending_documents,
        extract_version,
        reconcile_pending_extractions,
        link_opportunity,
        reconcile_lifecycle_links,
        compute_opportunity_delta,
        reconcile_pending_deltas,
        evaluate_company_opportunity,
        reconcile_eligibility_results,
        rank_company_opportunity,
        reconcile_ranking_results,
        func(deliver_notification, keep_result=0),
        dispatch_pending_notifications,
        reconcile_notifications,
    ]
    redis_settings = redis_settings()
    max_jobs = 10
    job_timeout = 60
    queue_name = WORKER_QUEUE
    on_startup = on_startup


class SchedulerSettings:
    health_check_interval = 30
    functions = [
        poll_source,
        ingest_record,
        reconcile_failed_jobs,
        reconcile_pending_normalizations,
        reconcile_pending_documents,
        extract_version,
        reconcile_pending_extractions,
        link_opportunity,
        reconcile_lifecycle_links,
        compute_opportunity_delta,
        reconcile_pending_deltas,
        evaluate_company_opportunity,
        reconcile_eligibility_results,
        rank_company_opportunity,
        reconcile_ranking_results,
        func(deliver_notification, keep_result=0),
        dispatch_pending_notifications,
        reconcile_notifications,
    ]
    redis_settings = redis_settings()
    cron_jobs = [
        cron(
            poll_configured_sources,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=True,
        ),
        cron(reconcile_failed_jobs, minute={1, 6, 11, 16, 21, 26, 31, 36, 41, 46, 51, 56}),
        cron(
            reconcile_pending_normalizations,
            minute={2, 7, 12, 17, 22, 27, 32, 37, 42, 47, 52, 57},
        ),
        cron(reconcile_pending_documents, minute={3, 8, 13, 18, 23, 28, 33, 38, 43, 48, 53, 58}),
        cron(
            reconcile_pending_extractions,
            minute={4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59},
            run_at_startup=True,
        ),
        cron(reconcile_lifecycle_links, minute={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(reconcile_pending_deltas, minute={5, 15, 25, 35, 45, 55}, run_at_startup=True),
        cron(reconcile_eligibility_results, minute={6, 16, 26, 36, 46, 56}, run_at_startup=True),
        cron(reconcile_ranking_results, minute={7, 17, 27, 37, 47, 57}, run_at_startup=True),
        cron(reconcile_notifications, minute={8, 18, 28, 38, 48, 58}, run_at_startup=True),
        cron(dispatch_pending_notifications, second={0, 30}, run_at_startup=True),
    ]
    max_jobs = 1
    queue_name = "arq:procure-delta:scheduler"
    on_startup = on_startup
