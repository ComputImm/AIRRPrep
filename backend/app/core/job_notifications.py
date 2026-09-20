"""
Where the launch gate and the two job emails are actually enforced.

Both start endpoints (bulk in main.py, single-cell in app/api/singlecell.py)
call :func:`attach_job_notification` before queueing work, and both Celery
tasks call :func:`notify_job_finished` when they reach a terminal state. That
keeps one copy of the rules:

* a run the estimator calls long may not start unless the session has a
  verified address — enforced here, server-side, because the frontend's
  pre-flight estimate is a UX affordance and not a control;
* any session that *has* verified an address gets the full treatment for
  every run, long or short. Verifying is therefore also how a user opts in
  to being emailed about quick jobs;
* a job with no verified address behaves exactly as it did before this
  feature existed.
"""

import logging

from app.config import redis_client
from app.core.email_verification import get_verified_email
from app.core.estimate import JobEstimate
from app.core.job_store import get_job, update_job
from app.core.notifications import send_job_finished, send_job_started
from app.core.session_store import get_session, update_session
from app.core.tracking import create_tracking_code

logger = logging.getLogger("app.job_notifications")


class JobNotificationRequired(Exception):
    """
    Raised when a run is too long to start without a verified address.

    Carries the estimate so the endpoint can tell the user *why* they are
    being asked — "roughly two hours, because of BuildConsensus" reads very
    differently from an unexplained demand for an email address.
    """

    def __init__(self, estimate: JobEstimate):
        super().__init__("Email verification is required to start this job.")
        self.estimate = estimate


def attach_job_notification(
    session_id: str,
    job_id: str,
    estimate: JobEstimate,
    route: str,
    label: str,
) -> str | None:
    """
    Apply the gate and, when the session has a verified address, give the job
    a tracking code and send the "your run has started" email.

    Returns the tracking code, or None when this session has no verified
    address and the run is short enough not to need one.

    Raises :class:`JobNotificationRequired` when the run is gated.
    """
    verified_email = get_verified_email(session_id)

    if not verified_email:
        if estimate.requires_email:
            raise JobNotificationRequired(estimate)
        return None

    tracking_code = create_tracking_code(
        session_id=session_id,
        job_id=job_id,
        email=verified_email,
        route=route,
        label=label,
    )

    # Recording the code is what switches this job document to the longer
    # TTL (see app/core/job_store.py) — it has to outlive the tab that
    # started it. The session is pushed out to match, so the token minted on
    # recovery still has a session to attach to.
    update_job(session_id, job_id, {
        "tracking_code": tracking_code,
        "notify_email": verified_email,
        "notify_route": route,
        "notify_label": label,
        "estimated_seconds": round(estimate.estimated_seconds),
    })
    session = get_session(session_id)
    if session:
        update_session(session)

    send_job_started(
        email=verified_email,
        tracking_code=tracking_code,
        job_label=label,
        estimated_seconds=estimate.estimated_seconds,
    )
    return tracking_code


def notify_job_finished(
    session_id: str,
    job_id: str,
    succeeded: bool,
    error: str | None = None,
) -> None:
    """
    Send the completion email for a tracked job. A no-op for jobs with no
    notification attached.

    Called from the Celery tasks, so it must never raise: a mail failure at
    this point would mark a perfectly good finished job as failed.
    """
    try:
        job = get_job(session_id, job_id) or {}
        email = job.get("notify_email")
        tracking_code = job.get("tracking_code")
        if not email or not tracking_code:
            return

        # Celery retries and the executor's own terminal-state handling can
        # both land here for one job; NX makes the first one win.
        if not redis_client.set(
            f"notified:{session_id}:{job_id}", "1", ex=86400, nx=True
        ):
            return

        send_job_finished(
            email=email,
            tracking_code=tracking_code,
            job_label=job.get("notify_label") or "preprocessing",
            succeeded=succeeded,
            error=error,
        )
    except Exception:
        logger.error(
            "Could not send completion email for job %s", job_id, exc_info=True
        )
