# app/core/uploads.py
"""
Transparent gzip handling for uploaded files.

`.gz` has always been in ALLOWED_UPLOAD_EXTENSIONS, but nothing ever
decompressed it — detect_file_type()/detect_capabilities() (and, later,
pRESTO's readSeqFile/BioPython SeqIO) all expect plaintext FASTQ/FASTA, so a
`.gz` upload silently produced garbage. Decompressing once, here, at the
upload boundary means every downstream consumer keeps seeing a plain
fastq/fasta file exactly as before.
"""

import gzip
import shutil
from pathlib import Path

from fastapi import HTTPException

from app.core.security import ALLOWED_UPLOAD_EXTENSIONS

_CHUNK_SIZE = 1024 * 1024


def maybe_decompress_gzip(path: Path, filename: str) -> tuple[Path, str]:
    """
    If `filename` ends in `.gz`, decompress `path` in place and return the
    new (path, filename) with the `.gz` suffix stripped. Otherwise return
    (path, filename) unchanged.

    Raises HTTPException(400) if the file isn't valid gzip data, or if the
    inner filename (after stripping `.gz`) doesn't itself have an allowed
    extension.
    """
    if Path(filename).suffix.lower() != ".gz":
        return path, filename

    inner_name = Path(filename).stem  # "reads.fastq.gz" -> "reads.fastq"
    inner_suffix = Path(inner_name).suffix.lower()
    if inner_suffix not in ALLOWED_UPLOAD_EXTENSIONS or inner_suffix == ".gz":
        raise HTTPException(
            status_code=400,
            detail=(
                "Compressed uploads must have a recognized inner extension, "
                "e.g. 'reads.fastq.gz'."
            ),
        )

    decompressed_path = path.with_name(inner_name)
    try:
        with gzip.open(path, "rb") as src, open(decompressed_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=_CHUNK_SIZE)
    except gzip.BadGzipFile:
        decompressed_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail="Uploaded .gz file is not valid gzip data"
        )
    except OSError as e:
        decompressed_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to decompress .gz file: {e}")

    path.unlink(missing_ok=True)
    return decompressed_path, inner_name
