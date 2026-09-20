# app/core/file_store.py
"""
The record of one uploaded file.

Two things beyond the path are recorded here, and both exist so a user does
not have to re-upload gigabytes to run a second pipeline:

* ``created_at`` / ``expires_at`` -- an upload is kept for
  ``UPLOAD_RETENTION_DAYS`` (see app/config.py) and then removed from disk as
  well as from Redis. The UI shows the remaining time so "reuse a file I
  already uploaded" is an informed choice rather than a gamble.
* ``size`` and ``session_id`` -- what a session's uploads add up to, which is
  what the per-session storage ceiling is checked against.

The Redis key carries the same TTL, so a record can never outlive the bytes it
describes; ``purge_expired_uploads`` handles the other direction, deleting
files whose record has already expired.
"""

from dataclasses import dataclass, asdict, field
from typing import List, Optional
from pathlib import Path
import json
import logging
import time
import uuid

from app.config import FILE_TTL, UPLOAD_RETENTION_SECONDS, redis_client
from app.pipeline.file_inspector import detect_file_type
from app.pipeline.file_inspector import detect_capabilities
from app.pipeline.file_inspector import detect_fields

logger = logging.getLogger(__name__)


@dataclass
class StoredFile:
    file_id: str
    original_name: str
    path: str
    file_type: str
    capabilities: List[str]
    #: Concrete annotation field names seen in the file's headers (e.g.
    #: BARCODE, PRIMER), the seed of the per-stage field registry in
    #: app/pipeline/planner.py. See fields_confident below.
    fields: List[str] = field(default_factory=list)
    #: False when `fields` may be incomplete -- e.g. a vendor header format
    #: not yet normalized by ConvertHeaders.*, or unparseable text. Downstream
    #: field-existence checks must not enforce against `fields` while this is
    #: False (see app/pipeline/file_inspector.py:inspect_headers).
    fields_confident: bool = False
    #: Bytes on disk, so a session's total can be summed without stat()ing.
    size: int = 0
    #: Unix timestamps. Defaulted so records written before these fields
    #: existed still load.
    created_at: float = 0.0
    expires_at: float = 0.0
    #: Owning session, used to list a session's uploads and to bound cleanup.
    session_id: Optional[str] = None

    def to_public_dict(self) -> dict:
        """What the API may show a client: never the server-side path."""
        return {
            "file_id": self.file_id,
            "filename": self.original_name,
            "file_type": self.file_type,
            "capabilities": list(self.capabilities),
            "fields": list(self.fields),
            "fields_confident": self.fields_confident,
            "size": self.size,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def _file_key(file_id: str) -> str:
    return f"file:{file_id}"


def save_file(
    file_path: Path,
    original_name: str,
    session_id: str | None = None,
) -> str:
    file_id = str(uuid.uuid4())

    file_type = detect_file_type(str(file_path))
    capabilities = detect_capabilities(str(file_path))
    fields, fields_confident = detect_fields(str(file_path))

    now = time.time()
    try:
        size = Path(file_path).stat().st_size
    except OSError:
        size = 0

    stored_file = StoredFile(
        file_id=file_id,
        original_name=original_name,
        path=str(file_path),
        file_type=file_type,
        capabilities=[cap.value for cap in capabilities],
        fields=sorted(fields),
        fields_confident=fields_confident,
        size=size,
        created_at=now,
        expires_at=now + UPLOAD_RETENTION_SECONDS,
        session_id=session_id,
    )

    redis_client.set(_file_key(file_id), json.dumps(asdict(stored_file)), ex=FILE_TTL)

    return file_id


def get_file(file_id: str) -> Optional[StoredFile]:
    data = redis_client.get(_file_key(file_id))

    if not data:
        return None

    file_dict = json.loads(data)
    # Records written before size/expiry existed are still readable.
    known = {f for f in StoredFile.__dataclass_fields__}
    return StoredFile(**{k: v for k, v in file_dict.items() if k in known})


def list_files() -> List[StoredFile]:
    files = []
    for key in redis_client.scan_iter("file:*"):
        data = redis_client.get(key)
        if data:
            file_dict = json.loads(data)
            known = {f for f in StoredFile.__dataclass_fields__}
            files.append(StoredFile(**{k: v for k, v in file_dict.items() if k in known}))
    return files


def get_files(file_ids: List[str]) -> List[StoredFile]:
    """Records for the given ids, skipping any that have already expired."""
    found = []
    for file_id in file_ids:
        stored = get_file(file_id)
        if stored is not None:
            found.append(stored)
    return found


def session_upload_bytes(file_ids: List[str]) -> int:
    """Total size of a session's live uploads."""
    return sum(f.size for f in get_files(file_ids))


def delete_file(file_id: str, remove_from_disk: bool = True) -> bool:
    """
    Forget an upload.

    The bytes go too by default: leaving them behind would mean a user who
    deleted a file from the UI still had it sitting on the server, and the
    retention promise would be false.
    """
    stored = get_file(file_id)
    if stored and remove_from_disk:
        _unlink(stored.path)
    return redis_client.delete(_file_key(file_id)) > 0


def _unlink(path: str) -> bool:
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except OSError as e:
        logger.warning("Could not delete upload %s: %s", path, e)
        return False


def purge_expired_uploads(upload_root: Path) -> dict:
    """
    Delete upload files whose Redis record is gone.

    Redis expires the record on its own, but nothing expires the bytes -- so
    without this the disk keeps every file ever uploaded while the API insists
    they were removed days ago. Walks the upload directory (never the job
    workspaces, which have their own lifetime) and removes any file older than
    the retention window that no live record points at.
    """
    upload_root = Path(upload_root)
    if not upload_root.exists():
        return {"scanned": 0, "deleted": 0, "freed_bytes": 0}

    live_paths = {str(Path(f.path).resolve()) for f in list_files()}
    cutoff = time.time() - UPLOAD_RETENTION_SECONDS

    scanned = deleted = freed = 0
    for path in upload_root.rglob("*"):
        if not path.is_file():
            continue
        scanned += 1
        try:
            stat = path.stat()
        except OSError:
            continue
        if str(path.resolve()) in live_paths:
            continue
        if stat.st_mtime > cutoff:
            # No record, but still inside the retention window: an upload
            # in flight, or one whose record is about to be written.
            continue
        if _unlink(str(path)):
            deleted += 1
            freed += stat.st_size

    # Leave the tree tidy: a session directory with nothing left in it.
    for directory in sorted(upload_root.glob("*"), reverse=True):
        if directory.is_dir():
            try:
                next(directory.iterdir())
            except StopIteration:
                directory.rmdir()
            except OSError:
                pass

    return {"scanned": scanned, "deleted": deleted, "freed_bytes": freed}
