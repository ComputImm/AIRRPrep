# app/api/notifications.py
"""
Endpoints behind the "this will take a while — leave us your email" flow.

    GET  /api/captcha/new         a fresh anti-bot challenge
    POST /api/jobs/estimate       how long will this run take, and is a
                                  verified address required before it starts?
    POST /api/email/request-code  mail a 6-digit code to an address
    POST /api/email/verify-code   confirm it
    GET  /api/email/status        which address (if any) this session verified
    POST /api/tracking/resume     trade a tracking code + address back for the
                                  session, so the user lands on their run

The two routes that can be abused without a session of the caller's own —
sending mail to an arbitrary address, and guessing at tracking codes — also
require a solved CAPTCHA on top of their rate limit. See app/core/captcha.py.

Everything except the resume route is session-scoped and needs the session
token. Resume deliberately is not: its whole purpose is to work from a
browser that has never seen this session — which is exactly why it demands
the tracking code *and* the address it was issued to, and why it is the most
tightly rate-limited route in the app.
"""

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.auth import (
    issue_additional_session_token,
    verify_session_token,
)
from app.core.captcha import CaptchaError, new_challenge, verify as verify_captcha
from app.core.email_verification import (
    EmailVerificationError,
    confirm_code,
    get_verified_email,
    normalize_email,
    request_code,
)
from app.core.estimate import estimate_bulk_job, estimate_singlecell_job
from app.core.file_store import get_file
from app.core.job_store import get_job
from app.core.notifications import send_verification_code
from app.core.rate_limit import limiter
from app.core.security import validate_identifier
from app.core.tracking import resolve_tracking, touch_tracking
from app.pipeline.parser import parse_steps
from app.singlecell.models import TRUST4_ASSEMBLY_FORMATS

logger = logging.getLogger("app")

router = APIRouter(tags=["notifications"])


def _require_session(session_id: str, token: str | None) -> str:
    """
    Session-token check for routes that carry `session_id` in the JSON body.

    app.core.auth.require_session_token is a dependency written for routes
    with `session_id` in the *path*; used here FastAPI would look for it as a
    query parameter instead, so these routes check explicitly — the same way
    main.py::start_pipeline does.
    """
    validate_identifier(session_id, "session_id")
    if not verify_session_token(session_id, token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")
    return session_id


# --- Anti-bot --------------------------------------------------------------

@router.get("/captcha/new")
@limiter.limit("30/minute")
async def captcha_new(request: Request):
    """Issue a fresh challenge. Public — it is the thing that proves you are
    not a script, so it cannot itself require having proved that."""
    challenge = new_challenge()
    return {
        "captcha_id": challenge.captcha_id,
        "image": challenge.image,
        "expires_in": challenge.expires_in,
    }


def _require_captcha(captcha_id: str | None, answer: str | None) -> None:
    try:
        verify_captcha(captcha_id or "", answer or "")
    except CaptchaError as e:
        # 400 with a distinct marker so the client knows to refresh the image
        # rather than just showing the text and leaving a stale challenge.
        raise HTTPException(
            status_code=400,
            detail={"error": "captcha_failed", "message": str(e)},
        )


# --- Estimate --------------------------------------------------------------

class EstimateRequest(BaseModel):
    session_id: str
    file_ids: list[str] = Field(default_factory=list)
    #: Bulk runs: the pipeline the user assembled, same shape as /jobs/start.
    steps: list[dict] = Field(default_factory=list)
    #: Single-cell runs: set this instead of `steps`.
    format_id: str | None = None


def _paths_for(file_ids: list[str]) -> list[str]:
    """Resolve uploaded file ids to on-disk paths, skipping any that have
    expired — a missing file is /jobs/start's error to report, not this
    endpoint's."""
    paths = []
    for file_id in file_ids:
        stored = get_file(file_id)
        if stored:
            paths.append(str(stored.path))
    return paths


@router.post("/jobs/estimate")
@limiter.limit("30/minute")
async def estimate_job(
    request: Request,
    body: EstimateRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    """
    Size a run before it is started.

    The frontend calls this when the user clicks Run: a cheap answer means it
    starts immediately, an expensive one means the email gate opens first.
    /jobs/start re-runs the same check server-side, so a client that skips
    this call gains nothing.
    """
    _require_session(body.session_id, x_session_token)
    paths = _paths_for(body.file_ids)

    if body.format_id:
        estimate = estimate_singlecell_job(
            paths, needs_assembly=body.format_id in TRUST4_ASSEMBLY_FORMATS
        )
    else:
        try:
            steps = parse_steps([dict(step) for step in body.steps])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        estimate = estimate_bulk_job(paths, steps)

    return {
        **estimate.to_dict(),
        "verified_email": get_verified_email(body.session_id),
    }


# --- Email verification ----------------------------------------------------

class RequestCodeBody(BaseModel):
    session_id: str
    email: str
    captcha_id: str | None = None
    captcha_answer: str | None = None


@router.post("/email/request-code")
@limiter.limit("5/minute")
async def email_request_code(
    request: Request,
    body: RequestCodeBody,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    _require_session(body.session_id, x_session_token)
    # This route sends mail to an address the caller chose — without a check
    # here it is a mail-bomb relay pointed at anyone.
    _require_captcha(body.captcha_id, body.captcha_answer)

    try:
        email = normalize_email(body.email)
        code = request_code(body.session_id, email)
    except EmailVerificationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # smtplib is blocking; keep it off the event loop. Sent inline rather than
    # queued because the Celery pool is busy running multi-hour pipelines and
    # a verification code stuck behind one would be useless.
    sent = await run_in_threadpool(send_verification_code, email, code)
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Could not send the verification email. Please try again.",
        )

    return {"sent": True, "email": email}


class VerifyCodeBody(BaseModel):
    session_id: str
    email: str
    code: str


@router.post("/email/verify-code")
@limiter.limit("10/minute")
async def email_verify_code(
    request: Request,
    body: VerifyCodeBody,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    _require_session(body.session_id, x_session_token)

    try:
        outcome = confirm_code(body.session_id, body.email, body.code)
    except EmailVerificationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not outcome.ok:
        raise HTTPException(status_code=400, detail=outcome.message)

    return {"verified": True, "email": normalize_email(body.email)}


@router.get("/email/status")
async def email_status(
    session_id: str = Query(...),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    _require_session(session_id, x_session_token)
    return {"verified_email": get_verified_email(session_id)}


# --- Tracking-code recovery ------------------------------------------------

class ResumeBody(BaseModel):
    code: str
    email: str
    captcha_id: str | None = None
    captcha_answer: str | None = None


@router.post("/tracking/resume")
@limiter.limit("10/minute")
async def resume_from_tracking_code(request: Request, body: ResumeBody):
    """
    Trade a tracking code plus the address it was issued to for access to the
    run it belongs to.

    Returns a freshly minted session token — the original is only stored
    hashed and cannot be handed back — which the client stores exactly as it
    would a new session's, so every subsequent status poll and download works
    unchanged. The tab that started the run keeps working too; see
    app/core/auth.py::issue_additional_session_token.

    Wrong code and wrong address give the same 404 on purpose: distinguishing
    them would confirm which codes exist.
    """
    # The CAPTCHA is checked before the lookup so a script cannot walk the
    # code space at all — the rate limit alone only slows that down.
    _require_captcha(body.captcha_id, body.captcha_answer)

    record = resolve_tracking(body.code, body.email)
    if not record:
        raise HTTPException(
            status_code=404,
            detail="No run found for that tracking code and email address.",
        )

    job = get_job(record.session_id, record.job_id)
    if not job:
        raise HTTPException(
            status_code=410,
            detail="That run has expired and its results are no longer available.",
        )

    token = issue_additional_session_token(record.session_id)
    if not token:
        raise HTTPException(
            status_code=410,
            detail="That session has expired and its results are no longer available.",
        )

    # Someone actively checking on a run should not have it expire underneath
    # them while they keep checking.
    touch_tracking(record.code)

    return {
        "session_id": record.session_id,
        "job_id": record.job_id,
        "session_token": token,
        "route": record.route,
        "label": record.label,
        "status": job.get("status"),
    }
