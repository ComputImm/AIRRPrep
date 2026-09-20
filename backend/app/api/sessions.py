from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import List
from app.services import session_service
from app.core.file_store import (
    delete_file,
    get_file,
    get_files,
    save_file,
    session_upload_bytes,
)
from app.core.auth import require_session_token
from app.core.security import (
    MAX_UPLOAD_SIZE_BYTES,
    safe_filename,
    validate_identifier,
    validate_upload_extension,
)
from app.core.uploads import maybe_decompress_gzip
from app.config import (
    MAX_SESSION_UPLOAD_BYTES,
    MAX_SESSION_UPLOAD_MB,
    UPLOAD_RETENTION_DAYS,
    UPLOADS_DIR,
)
from pydantic import BaseModel
import aiofiles


router = APIRouter()

class SessionResponse(BaseModel):
    session_id: str
    files: List[str]
    jobs: List[str]


class SessionCreateResponse(SessionResponse):
    # Only ever present in the create-session response — the client must
    # hold on to this; it cannot be retrieved again afterwards.
    session_token: str

@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session():
    """Create a new session"""
    session, token = session_service.create_session()
    return SessionCreateResponse(
        session_id=session.session_id,
        files=session.files,
        jobs=session.jobs,
        session_token=token,
    )

@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, _: str = Depends(require_session_token)):
    """Get session details"""
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        session_id=session.session_id,
        files=session.files,
        jobs=session.jobs
    )

@router.post("/sessions/{session_id}/files")
async def upload_file_to_session(
    session_id: str,
    file: UploadFile = File(...),
    _: str = Depends(require_session_token),
):
    """Upload a file to a session"""
    session_id = validate_identifier(session_id, "session_id")

    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Reject disallowed file types before touching disk.
    validate_upload_extension(file.filename)
    # Strip any "../" or other path components — only the basename survives.
    clean_filename = safe_filename(file.filename)

    # The per-file cap alone lets one session fill the disk a file at a time,
    # so what the session already holds is checked before accepting more.
    used = session_upload_bytes(session.files)
    if used >= MAX_SESSION_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"This session already stores its full {MAX_SESSION_UPLOAD_MB} MB "
                "of uploads. Delete a file you no longer need before uploading "
                "another."
            ),
        )
    remaining_quota = MAX_SESSION_UPLOAD_BYTES - used

    try:
        # ✅ اول فایل رو روی دیسک بنویس
        upload_dir = UPLOADS_DIR / session_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path = upload_dir / clean_filename
        size = 0
        limit = min(MAX_UPLOAD_SIZE_BYTES, remaining_quota)
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    await f.close()
                    file_path.unlink(missing_ok=True)
                    detail = (
                        "File too large"
                        if limit == MAX_UPLOAD_SIZE_BYTES
                        else (
                            "This file would exceed the session storage limit of "
                            f"{MAX_SESSION_UPLOAD_MB} MB"
                        )
                    )
                    raise HTTPException(status_code=413, detail=detail)
                await f.write(chunk)

        # Transparently decompress .gz uploads so everything downstream
        # (detect_file_type, pRESTO readSeqFile, single-cell adapters) only
        # ever sees plaintext fastq/fasta/csv/tsv.
        file_path, clean_filename = maybe_decompress_gzip(file_path, clean_filename)

        # ✅ حالا save_file رو صدا بزن (فایل روی دیسک هست)
        file_id = save_file(file_path, clean_filename, session_id=session_id)

        # ✅ file_id رو به session اضافه کن (نه file_path)
        session_service.add_file_to_session(session_id, file_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")

    stored = get_file(file_id)
    return {
        "session_id": session_id,
        "file_id": file_id,
        "file_path": str(file_path),
        "filename": file.filename,
        "expires_at": stored.expires_at if stored else None,
        "retention_days": UPLOAD_RETENTION_DAYS,
    }

@router.get("/sessions/{session_id}/files")
async def list_session_files(session_id: str, _: str = Depends(require_session_token)):
    """
    Every upload still held for this session, newest first.

    This is what makes "reuse a file I already uploaded" possible: the ids
    alone would tell the user nothing, so each entry carries the original file
    name, its detected format and annotations, its size, and when it will be
    deleted. Ids whose record has expired are dropped rather than listed as
    files that cannot actually be read.
    """
    session_id = validate_identifier(session_id, "session_id")
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stored = get_files(session.files)
    stored.sort(key=lambda f: f.created_at, reverse=True)
    used = sum(f.size for f in stored)

    return {
        "session_id": session_id,
        # Ids only, unchanged, for older callers.
        "files": [f.file_id for f in stored],
        "items": [f.to_public_dict() for f in stored],
        "retention_days": UPLOAD_RETENTION_DAYS,
        "storage": {
            "used_bytes": used,
            "limit_bytes": MAX_SESSION_UPLOAD_BYTES,
        },
    }


@router.delete("/sessions/{session_id}/files/{file_id}")
async def delete_session_file(
    session_id: str,
    file_id: str,
    _: str = Depends(require_session_token),
):
    """Delete one upload from this session, bytes included."""
    session_id = validate_identifier(session_id, "session_id")
    file_id = validate_identifier(file_id, "file_id")

    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if file_id not in session.files:
        raise HTTPException(status_code=404, detail="File not found in this session")

    delete_file(file_id)
    session.files = [f for f in session.files if f != file_id]
    session_service.update_session(session)
    return {"session_id": session_id, "file_id": file_id, "deleted": True}

@router.get("/sessions/{session_id}/jobs")
async def list_session_jobs(session_id: str, _: str = Depends(require_session_token)):
    """List all jobs in a session"""
    try:
        jobs = session_service.get_session_jobs(session_id)
        return {"session_id": session_id, "jobs": jobs}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: str = Depends(require_session_token)):
    """Delete a session"""
    session = session_service.get_session(session_id)
    # Take the uploads with it — a deleted session no one can authenticate to
    # again would otherwise leave its files on disk until the retention sweep.
    for file_id in (session.files if session else []):
        delete_file(file_id)

    success = session_service.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session deleted successfully"}
