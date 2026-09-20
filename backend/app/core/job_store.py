# app/core/job_store.py
import json
from app.config import redis_client, JOB_TTL, TRACKED_JOB_TTL


def _job_key(session_id, job_id):
    return f"session:{session_id}:job:{job_id}"


def _ttl_for(data) -> int:
    """
    How long this job document should live.

    A job the user is being emailed about is told to come back later with a
    tracking code, so it has to outlast the default one-day expiry — the code
    is worthless once the document it points at is gone. Derived from the
    document itself rather than passed in, so every existing update_job call
    site keeps the longer TTL alive without knowing about it.
    """
    return TRACKED_JOB_TTL if data.get("tracking_code") else JOB_TTL


def create_job(session_id, job_id, data):
    key = _job_key(session_id, job_id)
    redis_client.set(key, json.dumps(data), ex=_ttl_for(data))


def update_job(session_id, job_id, data):
    key = _job_key(session_id, job_id)
    existing = redis_client.get(key)
    merged = {**(json.loads(existing) if existing else {}), **data}
    redis_client.set(key, json.dumps(merged), ex=_ttl_for(merged))


def get_job(session_id, job_id):
    key = _job_key(session_id, job_id)
    data = redis_client.get(key)
    return json.loads(data) if data else None


# ── Cancellation ───────────────────────────────────────────────────────────
# A stop request is a separate key rather than a field on the job document,
# because the API process and the Celery worker both write the document and
# would otherwise race: the worker's next update_job merges its own stale copy
# over the flag the API just set. A dedicated key is only ever written by the
# API and only ever read by the worker, so neither can clobber the other.
#
# The worker checks between steps (see app/pipeline/executor.py), which is
# where a pRESTO step can be interrupted without leaving a half-written file.


def _cancel_key(session_id, job_id):
    return f"session:{session_id}:job:{job_id}:cancel"


def request_cancel(session_id, job_id) -> None:
    """Ask the worker to stop this job at the next step boundary."""
    redis_client.set(_cancel_key(session_id, job_id), "1", ex=TRACKED_JOB_TTL)


def is_cancel_requested(session_id, job_id) -> bool:
    return redis_client.exists(_cancel_key(session_id, job_id)) > 0


def clear_cancel(session_id, job_id) -> None:
    redis_client.delete(_cancel_key(session_id, job_id))
