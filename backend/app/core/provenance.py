"""
Provenance: what exactly produced a result.

Two things are recorded wherever a result or a reusable workflow leaves the
server:

* **files** by content, not by id -- original name, size and SHA-256 -- so a
  reader can tell whether the primer FASTA or 10x export they hold is the
  one that was used, even after the upload itself has expired;
* **software** by version -- the AIRRPrep release, the container image it
  ran in, pRESTO, TRUST4 and Python.

AIRRPREP_VERSION and AIRRPREP_IMAGE are set at build/deploy time (see the
Dockerfile); a development checkout reports "dev" and no image.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
from pathlib import Path

_CHUNK = 1 << 20


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: str | Path, name: str | None = None) -> dict:
    """{name, size_bytes, sha256} for one file on disk."""
    p = Path(path)
    return {
        "name": name or p.name,
        "size_bytes": p.stat().st_size,
        "sha256": sha256_file(p),
    }


def _package_version(dist: str) -> str | None:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def software_versions() -> dict:
    return {
        "airrprep": os.getenv("AIRRPREP_VERSION", "dev"),
        "container_image": os.getenv("AIRRPREP_IMAGE") or None,
        "presto": _package_version("presto"),
        "trust4": os.getenv("TRUST4_VERSION") or None,
        "python": platform.python_version(),
    }
