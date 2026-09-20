# app/core/auth.py
"""
Lightweight per-session authentication.

This app has no user accounts — a "session" is just a bag of uploads/jobs
identified by a uuid. Without this, anyone who learns/guesses a session_id
(they're visible in URLs, logs, browser history, Referer headers, etc.) can
read and download that session's files. To close that off, each session
gets a random secret token when it's created; every subsequent request that
touches that session must present the token.

The token is returned to the client exactly once, at session-creation time.
Only its SHA-256 hash is ever stored (in Redis, via SessionData.token_hash),
so a Redis compromise alone does not expose usable tokens.
"""

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException, Query

from app.core.session_store import add_token_hash, get_session


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tokens_match(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash)


def verify_session_token(session_id: str, token: str | None) -> bool:
    if not token:
        return False
    session = get_session(session_id)
    if not session:
        return False

    # The creation-time token, plus any minted later by a tracking-code
    # recovery — a session legitimately has several live tokens once the user
    # has come back to it from a second device.
    candidates = [
        h for h in
        [getattr(session, "token_hash", None), *getattr(session, "extra_token_hashes", [])]
        if h
    ]
    return any(_tokens_match(token, expected) for expected in candidates)


def issue_additional_session_token(session_id: str) -> str | None:
    """
    Mint a second token for an existing session and return the plaintext.

    Needed by tracking-code recovery: only token hashes are stored, so the
    original token cannot be given back — a new one is issued and registered
    alongside it. Returns None if the session no longer exists.
    """
    token = generate_session_token()
    if not add_token_hash(session_id, hash_token(token)):
        return None
    return token


async def require_session_token(
    session_id: str,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
    token: str | None = Query(
        default=None,
        description="Session token — only needed when a header can't be set (e.g. plain download links).",
    ),
) -> str:
    """
    FastAPI dependency for any route with `session_id` as a path parameter.

    Accepts the token either via the `X-Session-Token` header (used by
    fetch/XHR calls, the normal case) or a `token` query parameter (needed
    for plain `<a href>` file-download links, which can't set headers).
    """
    supplied = x_session_token or token
    if not verify_session_token(session_id, supplied):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")
    return session_id
