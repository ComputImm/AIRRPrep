import uuid
from typing import Optional, List
from app.core.session_store import (
    SessionData,
    create_session as store_create_session,
    get_session as store_get_session,
    update_session as store_update_session,
    add_file,
    add_job,
    list_session_files,
    list_session_jobs,
    delete_session as store_delete_session
)
from app.core.auth import generate_session_token, hash_token

def create_session() -> tuple[SessionData, str]:
    """Create a new session. Returns (session, plaintext_token) — the
    plaintext token is only available here, right after creation."""
    session_id = str(uuid.uuid4())
    token = generate_session_token()
    session = store_create_session(session_id, token_hash=hash_token(token))
    return session, token

def get_session(session_id: str) -> Optional[SessionData]:
    """Get session by ID"""
    return store_get_session(session_id)

def update_session(session: SessionData) -> None:
    """Persist a mutated session record (e.g. after removing a file)."""
    store_update_session(session)

def add_file_to_session(session_id: str, file_id: str) -> None:
    """Add a file to session"""
    success = add_file(session_id, file_id)
    if not success:
        raise ValueError(f"Session {session_id} not found")

def add_job_to_session(session_id: str, job_id: str) -> None:
    """Add a job to session"""
    success = add_job(session_id, job_id)
    if not success:
        raise ValueError(f"Session {session_id} not found")

def get_session_files(session_id: str) -> List[str]:
    """Get all files in a session"""
    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    return list_session_files(session_id)

def get_session_jobs(session_id: str) -> List[str]:
    """Get all jobs in a session"""
    session = get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    return list_session_jobs(session_id)

def delete_session(session_id: str) -> bool:
    """Delete a session"""
    return store_delete_session(session_id)
