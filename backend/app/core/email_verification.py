"""
Email ownership check: a 6-digit code, mailed to the address, entered back.

Only reachability is being proven here — that a finished-job notification
will actually arrive somewhere the user reads. There are still no accounts;
the verified address is recorded on the session (SessionData.verified_email)
and is what later gets paired with a tracking code to unlock a job's results.

The code itself is stored hashed, for the same reason session tokens are: a
Redis dump should not hand out live credentials.

Guardrails, all configurable in app/config.py:

* codes expire (EMAIL_CODE_TTL);
* wrong guesses are counted and the code is burned after
  EMAIL_CODE_MAX_ATTEMPTS, so 6 digits cannot be walked through;
* a resend cooldown (EMAIL_CODE_RESEND_COOLDOWN) stops the endpoint being
  used to mail-bomb a third party.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass

from app.config import (
    EMAIL_CODE_MAX_ATTEMPTS,
    EMAIL_CODE_RESEND_COOLDOWN,
    EMAIL_CODE_TTL,
    EMAIL_HASH_SECRET,
    redis_client,
)
from app.core.session_store import get_session, update_session

logger = logging.getLogger(__name__)

_DEV_KEY = "secret:email_hash_dev_key"
_warned_dev_key = False

# Intentionally permissive. The code round-trip is the real check; this only
# catches typos and obvious junk before an email is attempted.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

_CODE_DIGITS = 6


class EmailVerificationError(Exception):
    """Raised for every user-correctable problem in this module."""


@dataclass
class VerificationOutcome:
    ok: bool
    message: str = ""
    #: Seconds the caller must wait before a resend is allowed.
    retry_after: int = 0
    #: Guesses left on the current code.
    attempts_remaining: int = 0


def normalize_email(email: str) -> str:
    """Lowercased and trimmed — the form used for storage and comparison."""
    cleaned = (email or "").strip().lower()
    if not _EMAIL_RE.match(cleaned) or len(cleaned) > 254:
        raise EmailVerificationError("That does not look like an email address.")
    return cleaned


def _email_hash_key() -> bytes:
    """The HMAC key for hash_email: EMAIL_HASH_SECRET, or a dev fallback."""
    if EMAIL_HASH_SECRET:
        return EMAIL_HASH_SECRET.encode("utf-8")
    # Development only. Stored in Redis so it survives restarts; that puts it
    # beside the hashes it protects, which is exactly why production must set
    # EMAIL_HASH_SECRET instead.
    global _warned_dev_key
    if not _warned_dev_key:
        logger.warning(
            "EMAIL_HASH_SECRET is not set; using a development key stored in "
            "Redis. Set EMAIL_HASH_SECRET in production."
        )
        _warned_dev_key = True
    redis_client.set(_DEV_KEY, secrets.token_hex(32), nx=True)
    return redis_client.get(_DEV_KEY).encode("utf-8")


def hash_email(email: str) -> str:
    """
    Keyed HMAC-SHA256 of the normalized address.

    Used as the lookup value on a tracking record. Unlike a bare SHA-256, it
    cannot be reversed by hashing a list of candidate addresses without the
    server-side key.
    """
    return hmac.new(
        _email_hash_key(),
        normalize_email(email).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _hash_code(session_id: str, code: str) -> str:
    # Salted with the session id so an attacker who reads one hash learns
    # nothing about the same code issued to a different session.
    return hashlib.sha256(f"{session_id}:{code}".encode("utf-8")).hexdigest()


def _key(session_id: str) -> str:
    return f"emailverify:{session_id}"


def _generate_code() -> str:
    return f"{secrets.randbelow(10 ** _CODE_DIGITS):0{_CODE_DIGITS}d}"


def request_code(session_id: str, email: str) -> str:
    """
    Issue a fresh code for this session/address and return it so the caller
    can mail it. Raises EmailVerificationError if a resend is too soon.

    The plaintext code is returned but never stored.
    """
    email = normalize_email(email)
    key = _key(session_id)

    existing = redis_client.get(key)
    if existing:
        record = json.loads(existing)
        waited = time.time() - record.get("sent_at", 0)
        if waited < EMAIL_CODE_RESEND_COOLDOWN:
            raise EmailVerificationError(
                f"A code was just sent. Try again in "
                f"{int(EMAIL_CODE_RESEND_COOLDOWN - waited)} seconds."
            )

    code = _generate_code()
    redis_client.set(
        key,
        json.dumps({
            "email": email,
            "code_hash": _hash_code(session_id, code),
            "sent_at": time.time(),
            "attempts": 0,
        }),
        ex=EMAIL_CODE_TTL,
    )
    return code


def confirm_code(session_id: str, email: str, code: str) -> VerificationOutcome:
    """
    Check a submitted code. On success the address is recorded as verified on
    the session and the pending code is discarded.
    """
    email = normalize_email(email)
    key = _key(session_id)

    raw = redis_client.get(key)
    if not raw:
        return VerificationOutcome(
            ok=False, message="That code has expired. Request a new one."
        )

    record = json.loads(raw)

    if record.get("email") != email:
        return VerificationOutcome(
            ok=False,
            message="That code was sent to a different address.",
        )

    submitted = (code or "").strip()
    if not hmac.compare_digest(_hash_code(session_id, submitted),
                               record.get("code_hash", "")):
        attempts = int(record.get("attempts", 0)) + 1
        remaining = EMAIL_CODE_MAX_ATTEMPTS - attempts
        if remaining <= 0:
            # Burn the code rather than let it be brute-forced.
            redis_client.delete(key)
            return VerificationOutcome(
                ok=False,
                message="Too many incorrect attempts. Request a new code.",
            )
        record["attempts"] = attempts
        # Preserve the original expiry — a wrong guess must not extend the
        # code's life.
        ttl = redis_client.ttl(key)
        redis_client.set(
            key, json.dumps(record), ex=ttl if ttl and ttl > 0 else EMAIL_CODE_TTL
        )
        return VerificationOutcome(
            ok=False,
            message=f"Incorrect code. {remaining} attempt"
                    f"{'s' if remaining != 1 else ''} left.",
            attempts_remaining=remaining,
        )

    session = get_session(session_id)
    if not session:
        return VerificationOutcome(ok=False, message="Session not found.")

    session.verified_email = email
    update_session(session)
    redis_client.delete(key)

    return VerificationOutcome(ok=True, message="Email verified.")


def get_verified_email(session_id: str) -> str | None:
    """The address this session has already verified, if any."""
    session = get_session(session_id)
    return getattr(session, "verified_email", None) if session else None
