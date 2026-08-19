import logging
from decimal import Decimal

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from django.utils import timezone

from .algorithms import registry
from .models import Layout, PackingJob
from .notifications import publish_notification

logger = logging.getLogger(__name__)


def metrics_from_snapshot(snapshot, payload):
    container = snapshot["container"]
    box_by_id = {str(box["id"]): box for box in snapshot["boxes"]}
    packed_volume = sum(
        item["size_mm"]["length"] * item["size_mm"]["width"] * item["size_mm"]["height"]
        for item in payload["placements"]
    )
    container_volume = (
        container["length_mm"] * container["width_mm"] * container["height_mm"]
    )
    total_weight = sum(
        Decimal(str(box_by_id[item["box_id"]]["weight_kg"]))
        for item in payload["placements"]
    )
    capacity = container.get("max_weight_kg")
    return {
        "volume_utilization_pct": round(packed_volume * 100 / container_volume, 2),
        "packed_count": len(payload["placements"]),
        "unplaced_count": sum(item["count"] for item in payload["unplaced"]),
        "total_weight_kg": float(total_weight),
        "weight_utilization_pct": None
        if capacity in (None, 0, 0.0, "0", "0.000")
        else round(float(total_weight) * 100 / float(capacity), 2),
        "container_volume_mm3": container_volume,
    }


@shared_task(bind=True)
def run_packing_job(self, job_id):
    try:
        with transaction.atomic():
            job = (
                PackingJob.objects.select_for_update()
                .select_related("created_by")
                .get(id=job_id)
            )
            if job.status != PackingJob.Status.QUEUED:
                return
            job.status = PackingJob.Status.RUNNING
            job.started_at = timezone.now()
            job.progress = 0
            job.save(update_fields=["status", "started_at", "progress", "updated_at"])
        publish_notification(job.created_by, "packing_job.updated", job_payload(job))

        last_progress = 0

        def cancel_check():
            return PackingJob.objects.filter(
                id=job_id, status=PackingJob.Status.CANCELLED
            ).exists()

        def report_progress(value):
            nonlocal last_progress
            value = max(0, min(100, int(value)))
            if value >= last_progress + 5 or value == 100:
                PackingJob.objects.filter(
                    id=job_id, status=PackingJob.Status.RUNNING
                ).update(progress=value)
                last_progress = value

        definition = registry.get(job.algorithm)
        solution = definition.runner(
            job.input_snapshot, job.parameters, cancel_check, report_progress
        )
        payload = solution.as_payload()
        metrics = metrics_from_snapshot(job.input_snapshot, payload)

        with transaction.atomic():
            job = (
                PackingJob.objects.select_for_update()
                .select_related("created_by")
                .get(id=job_id)
            )
            if job.status == PackingJob.Status.CANCELLED:
                return
            layout = Layout.objects.create(
                project=job.project,
                source=Layout.Source.ALGORITHM,
                job=job,
                placements=payload,
                metrics=metrics,
            )
            job.status = PackingJob.Status.SUCCEEDED
            job.progress = 100
            job.finished_at = timezone.now()
            job.error_message = ""
            job.save(
                update_fields=[
                    "status",
                    "progress",
                    "finished_at",
                    "error_message",
                    "updated_at",
                ]
            )
        publish_notification(
            job.created_by, "packing_job.updated", job_payload(job, layout.id)
        )
    except InterruptedError:
        PackingJob.objects.filter(id=job_id).update(
            status=PackingJob.Status.CANCELLED, finished_at=timezone.now()
        )
    except SoftTimeLimitExceeded:
        fail_job(job_id, "Packing exceeded the configured time limit.")
        raise
    except PackingJob.DoesNotExist:
        logger.info("Packing job %s no longer exists", job_id)
    except Exception as exc:
        logger.exception("Packing job %s failed", job_id)
        fail_job(job_id, str(exc)[:2000] or "Unexpected packing error.")
        raise


def fail_job(job_id, message):
    job = PackingJob.objects.select_related("created_by").filter(id=job_id).first()
    if not job or job.status not in (
        PackingJob.Status.QUEUED,
        PackingJob.Status.RUNNING,
    ):
        return
    job.status = PackingJob.Status.FAILED
    job.error_message = message
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    publish_notification(job.created_by, "packing_job.updated", job_payload(job))


def job_payload(job, layout_id=None):
    return {
        "job_id": str(job.id),
        "status": job.status,
        "progress": job.progress,
        "layout_id": str(layout_id) if layout_id else None,
    }
