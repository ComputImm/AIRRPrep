# app/core/session_store.py
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import uuid
import json

from app.config import redis_client, SESSION_TTL


@dataclass
class SessionData:
    session_id: str
    files: List[str] = field(default_factory=list)
    jobs: List[str] = field(default_factory=list)
    # SHA-256 hash of the per-session secret token (see app/core/auth.py).
    # The plaintext token is only ever returned once, at creation time —
    # never persisted or logged.
    token_hash: Optional[str] = None
    # Hashes of additional tokens minted when a user returns via a tracking
    # code (app/core/tracking.py). Because only hashes are stored, the
    # original token cannot be handed back on recovery — so a fresh one is
    # issued and added here. Keeping the first hash valid means recovering on
    # a phone does not log the desktop tab out mid-run.
    extra_token_hashes: List[str] = field(default_factory=list)
    # Address confirmed via app/core/email_verification.py. Its presence is
    # what lets a long-running job start, and it is who gets notified.
    verified_email: Optional[str] = None


def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


def create_session(session_id, token_hash: str) -> SessionData:

    session = SessionData(session_id, token_hash=token_hash)

    key = _session_key(session.session_id)
    redis_client.set(key, json.dumps(asdict(session)), ex=SESSION_TTL)

    return session


def get_session(session_id: str) -> Optional[SessionData]:
    key = _session_key(session_id)
    data = redis_client.get(key)
    
    if not data:
        return None
    
    session_dict = json.loads(data)
    return SessionData(**session_dict)


def update_session(session: SessionData) -> None:
    key = _session_key(session.session_id)
    redis_client.set(key, json.dumps(asdict(session)), ex=SESSION_TTL)


def add_file(session_id: str, file_id: str) -> bool:
    session = get_session(session_id)
    if not session:
        return False
    
    if file_id not in session.files:
        session.files.append(file_id)
        update_session(session)
    
    return True


def add_job(session_id: str, job_id: str) -> bool:
    session = get_session(session_id)
    if not session:
        return False
    
    if job_id not in session.jobs:
        session.jobs.append(job_id)
        update_session(session)
    
    return True


def add_token_hash(session_id: str, token_hash: str) -> bool:
    """Register an additional valid token for this session (see the field
    comment on SessionData.extra_token_hashes)."""
    session = get_session(session_id)
    if not session:
        return False

    if token_hash not in session.extra_token_hashes:
        session.extra_token_hashes.append(token_hash)
        # Cap the list so repeated recoveries cannot grow the record without
        # bound; the oldest extra token is dropped first.
        session.extra_token_hashes = session.extra_token_hashes[-10:]
        update_session(session)

    return True


def delete_session(session_id: str) -> bool:
    key = _session_key(session_id)
    return redis_client.delete(key) > 0


def list_session_files(session_id: str) -> List[str]:
    session = get_session(session_id)
    return session.files if session else []


def list_session_jobs(session_id: str) -> List[str]:
    session = get_session(session_id)
    return session.jobs if session else []
