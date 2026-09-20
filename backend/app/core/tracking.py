"""
Tracking codes: the short number a user quotes to get back to a run.

A job started from an email-gated launch gets a 6-digit code. Emailed to the
user at start and again at finish, it is how they return to their results
later — from a different browser, a different machine, days after the tab
that started the run is gone.

**The code alone is not a credential.** Six digits is a millon-wide space,
which a script walks through in minutes; on its own it would leak other
people's sequencing results. Recovery therefore requires the code *and* the
address it was issued to, and the stored record keeps only a keyed HMAC of
the address (key: EMAIL_HASH_SECRET, held outside Redis), so the tracking
record never holds a directly usable pair. The lookup is
additionally rate limited at the route (see app/api/notifications.py).

``route`` is the frontend path the run was launched from. Recovery replays
the user onto that exact page with the job selected, which is why a resumed
run looks the same as one watched live rather than landing on some generic
results screen.
"""

import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass

from app.config import TRACKED_JOB_TTL, redis_client
from app.core.email_verification import hash_email

_CODE_DIGITS = 6
# Bounded so a saturated code space can't spin here forever; in practice the
# first candidate is free.
_MAX_ALLOCATION_ATTEMPTS = 20


@dataclass
class TrackingRecord:
    code: str
    session_id: str
    job_id: str
    email_hash: str
    #: Frontend path the run was started from, e.g. "/pipeline/umi-miseq-2x250".
    route: str
    #: Human label for the run, used in the emails.
    label: str
    created_at: float


def _key(code: str) -> str:
    return f"track:{code}"


def _new_code() -> str:
    return f"{secrets.randbelow(10 ** _CODE_DIGITS):0{_CODE_DIGITS}d}"


def create_tracking_code(
    session_id: str,
    job_id: str,
    email: str,
    route: str,
    label: str,
) -> str:
    """Allocate an unused code for this job and persist the record."""
    record = TrackingRecord(
        code="",
        session_id=session_id,
        job_id=job_id,
        email_hash=hash_email(email),
        route=route,
        label=label,
        created_at=time.time(),
    )

    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        code = _new_code()
        record.code = code
        # NX makes allocation atomic: two jobs starting at once can never be
        # handed the same code.
        if redis_client.set(
            _key(code), json.dumps(asdict(record)), ex=TRACKED_JOB_TTL, nx=True
        ):
            return code

    raise RuntimeError("Could not allocate a tracking code")


def get_tracking(code: str) -> TrackingRecord | None:
    """Look up a record by code alone — for internal use only.

    Anything reachable from a request must go through ``resolve_tracking``,
    which also demands the email address.
    """
    raw = redis_client.get(_key((code or "").strip()))
    if not raw:
        return None
    return TrackingRecord(**json.loads(raw))


def resolve_tracking(code: str, email: str) -> TrackingRecord | None:
    """
    Return the record only when the code and the address it was issued to
    both match. Returns None on any mismatch — the caller must not
    distinguish "no such code" from "wrong address", or the endpoint becomes
    an oracle for which codes exist.
    """
    record = get_tracking(code)
    if not record:
        return None
    try:
        supplied = hash_email(email)
    except Exception:
        return None
    if not hmac.compare_digest(supplied, record.email_hash):
        return None
    return record


def touch_tracking(code: str) -> None:
    """Refresh a record's TTL so an actively checked job does not expire."""
    redis_client.expire(_key(code), TRACKED_JOB_TTL)
