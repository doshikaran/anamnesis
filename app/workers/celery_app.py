"""
Celery app config. Queues and beat schedule for sync, analysis, insights, notifications, maintenance.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "anamnesis",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.sync_tasks",
        "app.workers.analysis_tasks",
        "app.workers.insight_tasks",
        "app.workers.notification_tasks",
        "app.workers.maintenance_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Queues
celery_app.conf.task_queues = {
    "default": {"exchange": "default", "routing_key": "default"},
    "sync": {"exchange": "sync", "routing_key": "sync"},
    "analysis": {"exchange": "analysis", "routing_key": "analysis"},
    "insights": {"exchange": "insights", "routing_key": "insights"},
    "notifications": {"exchange": "notifications", "routing_key": "notifications"},
    "maintenance": {"exchange": "maintenance", "routing_key": "maintenance"},
}

celery_app.conf.task_routes = {
    "app.workers.sync_tasks.*": {"queue": "sync"},
    "app.workers.analysis_tasks.*": {"queue": "analysis"},
    "app.workers.insight_tasks.*": {"queue": "insights"},
    "app.workers.notification_tasks.*": {"queue": "notifications"},
    "app.workers.maintenance_tasks.*": {"queue": "maintenance"},
}

# Beat schedule
celery_app.conf.beat_schedule = {
    "sync-all-connections": {
        "task": "app.workers.sync_tasks.sync_all_active_connections",
        "schedule": crontab(minute="*/30"),
    },
    "send-morning-briefings": {
        "task": "app.workers.insight_tasks.send_due_briefings",
        "schedule": crontab(minute="*"),
    },
    "schedule-nudges": {
        "task": "app.workers.insight_tasks.schedule_commitment_nudges",
        "schedule": crontab(minute=0),
    },
    "recalculate-people-scores": {
        "task": "app.workers.analysis_tasks.recalculate_all_people_scores",
        "schedule": crontab(hour=3, minute=0),
    },
    "generate-nightly-insights": {
        "task": "app.workers.insight_tasks.generate_pattern_insights",
        "schedule": crontab(hour=2, minute=0),
    },
    "merge-duplicate-people": {
        "task": "app.workers.maintenance_tasks.find_and_merge_duplicates",
        "schedule": crontab(hour=4, minute=0),
    },
    "send-pending-notifications": {
        "task": "app.workers.notification_tasks.send_pending_notifications",
        "schedule": crontab(minute="*"),
    },
    "enforce-data-retention": {
        "task": "app.workers.maintenance_tasks.enforce_data_retention",
        "schedule": crontab(hour=5, minute=0),
    },
}
