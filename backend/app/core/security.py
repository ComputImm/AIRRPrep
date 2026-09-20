# app/core/security.py
"""
Security helper functions shared across the API layer.

Centralizes the checks that prevent the most common issues found in this
codebase: path traversal (via user-supplied filenames, session/job ids, or
download paths) and unrestricted file uploads.
"""

import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException

# Only allow bioinformatics sequence file extensions to be uploaded.
# .csv/.tsv/.bam support Single-Cell adapter inputs (Cell Ranger annotations/
# AIRR TSV, TRUST4 barcode reports, 10x BAM); .gz uploads are transparently
# decompressed at upload time (see app/core/uploads.py).
ALLOWED_UPLOAD_EXTENSIONS = {
    ".fastq", ".fq", ".fasta", ".fa", ".fas",
    ".csv", ".tsv", ".bam",
    ".gz",
}

# Hard cap on a single uploaded file. Also enforced at the proxy/server level.
# Raw single-cell reads (10x FASTQ/BAM headed for TRUST4) run far larger than
# the assembled inputs this started out sized for, so the cap is deployment
# -configurable via MAX_UPLOAD_SIZE_MB.
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "200")) * 1024 * 1024

# session_id / job_id are generated with uuid4() by this codebase — enforce
# that shape everywhere they are used to build filesystem paths so a request
# can never smuggle "../" (or an absolute path) into JOBS_DIR.
_ID_RE = re.compile(r"^[a-fA-F0-9-]{8,64}$")


def is_safe_identifier(value: str) -> bool:
    """True if value is safe to use as a single path segment (uuid-like)."""
    if not value or "/" in value or "\\" in value or ".." in value:
        return False
    return bool(_ID_RE.match(value))


def validate_identifier(value: str, label: str = "id") -> str:
    """Raise 400 if value is not a safe path segment; otherwise return it."""
    if not is_safe_identifier(value):
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return value


def safe_filename(filename: str) -> str:
    """
    Strip any directory components and dangerous characters from a
    user-supplied filename, keeping only a safe basename.
    """
    name = Path(filename).name  # drops any "../" or absolute path prefix
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    name = name.lstrip(".") or "file"
    return name[:255]


def validate_upload_extension(filename: str) -> str:
    """Raise 400 if the extension isn't an allowed sequence file type."""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{suffix}' is not allowed. "
                f"Allowed types: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
            ),
        )
    return suffix


def resolve_within(base_path: Path, relative: str) -> Path:
    """
    Resolve `relative` against `base_path` and guarantee the result stays
    inside `base_path`. Raises 400 on any attempt to escape it (e.g. via
    "../", an absolute path, or a symlink).
    """
    base_resolved = base_path.resolve()
    candidate = (base_path / relative).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


def new_uuid() -> str:
    return str(uuid.uuid4())
