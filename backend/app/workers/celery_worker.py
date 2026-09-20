from app.pipeline.executor import run_pipeline
from celery import Celery
import logging
import time
import traceback
from pathlib import Path

from Bio import SeqIO
from app.config import REDIS_URL, UPLOAD_RETENTION_DAYS, UPLOADS_DIR
from app.core.job_notifications import notify_job_finished
from app.core.job_store import clear_cancel, update_job, get_job
from app.pipeline.executor import JobCancelled, run_pipeline
from app.pipeline.parser import parse_steps
from app.pipeline.file_inspector import (
    detect_file_type
)

import multiprocessing

logger = logging.getLogger("celery_worker")

# REDIS_URL comes from the environment (see app/config.py) so this points at
# the right broker whether running locally or inside docker-compose — it
# must never be hardcoded to localhost, or the worker silently can't reach
# the broker/backend used by the API container.
celery = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)



@celery.task
def test_task():

    time.sleep(5)

    return "task completed"


@celery.task
def purge_expired_uploads_task(upload_root: str | None = None):
    """
    Delete uploads past the retention window.

    Redis expires the file *record* by itself, but nothing expires the bytes,
    so without this sweep the disk keeps every file ever uploaded while the API
    tells users their data was removed days ago. Scheduled below; also safe to
    trigger by hand.
    """
    from app.core.file_store import purge_expired_uploads

    result = purge_expired_uploads(Path(upload_root) if upload_root else UPLOADS_DIR)
    logger.info(
        "Upload retention sweep (%s day window): %s",
        UPLOAD_RETENTION_DAYS,
        result,
    )
    return result


# Runs daily. The window itself is UPLOAD_RETENTION_DAYS, so an hourly sweep
# would only add load without deleting anything sooner. Needs `celery beat`
# alongside the worker; without it the task simply never fires and files
# linger, which is why the API never promises deletion earlier than this.
celery.conf.beat_schedule = {
    "purge-expired-uploads": {
        "task": "app.workers.celery_worker.purge_expired_uploads_task",
        "schedule": 24 * 60 * 60.0,
    },
}


@celery.task
def process_file(
    input_files,
    output_file,
    job_id,
    steps,
    session_id,
    convert_to_fasta=False,
    run_stem=None,
):

    try:
        if isinstance(input_files, str):
            input_files = [input_files]

        update_job(session_id, job_id, {
            "status": "PROCESSING",
            "session_id": session_id,
            "file_paths": input_files,
        })

        file_type = detect_file_type(input_files[0])

        parsed_steps = parse_steps(steps)

        result = run_pipeline(
            input_files=input_files,
            output_file=output_file,
            steps=parsed_steps,
            job_id=job_id,
            session_id=session_id,
            file_type=file_type,
            convert_to_fasta=convert_to_fasta,
            run_stem=run_stem,
        )
        if result:

            # A stop that arrived while the last step was already finishing has
            # nothing left to interrupt. Clearing the flag here is what stops
            # the UI showing "Stopping..." over a run that is plainly complete.
            clear_cancel(session_id, job_id)
            update_job(session_id, job_id, {
                "status": "DONE",
                "output_file": result,
                "cancel_requested": False,
            })
            # No-op unless this job carries a tracking code; see
            # app/core/job_notifications.py.
            notify_job_finished(session_id, job_id, succeeded=True)

    except JobCancelled as e:
        # The user asked to stop. run_pipeline already recorded the CANCELLED
        # status and the steps that did finish; this is not a failure and the
        # user does not need an email about a run they stopped themselves.
        logger.info("Job %s cancelled: %s", job_id, e)
        clear_cancel(session_id, job_id)

    except Exception as e:
        # Full traceback goes to the server logs only; clients only ever
        # see a short message so internal paths/stack details never leak.
        logger.error("Job %s failed: %s", job_id, traceback.format_exc())
        update_job(session_id, job_id, {
            "status": "FAILED",
            "error": f"Processing failed: {e}"
        })
        # A user who was told to walk away needs to hear about the failure
        # too, or they wait for an email that is never coming.
        notify_job_finished(
            session_id, job_id, succeeded=False, error=f"Processing failed: {e}"
        )
    except BaseException as e:
        error_msg = str(e)
    
        if isinstance(e, SystemExit) and "ERROR>" in error_msg:
            # استخراج بخش بعد از ERROR>
            parts = error_msg.split("ERROR>")
            if len(parts) > 1:
                error_msg = parts[1].strip()
            # اگر خیلی طولانی بود، کوتاه کن
            if len(error_msg) > 200:
                error_msg = error_msg[:200] + "..."
        logger.error("Job %s failed: %s", job_id, traceback.format_exc())
        update_job(session_id, job_id, {
            "status": "FAILED",
            "error": f"Processing failed: {e}"
        })
        notify_job_finished(session_id, job_id, succeeded=False, error=f"Processing failed: {e}")


# Registers process_single_cell_input on this same Celery app so the worker
# process (started as `celery -A app.workers.celery_worker worker`) picks it
# up — imported at the bottom to avoid a circular import (tasks.py imports
# `celery` from this module).
from app.singlecell import tasks as _singlecell_tasks  # noqa: E402,F401