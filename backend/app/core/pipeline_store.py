"""
Saved pipelines: a workflow the user built, kept so it can be run again.

Building a pipeline in the UI is the slow part -- a dozen steps, each with
parameters chosen against a particular library prep. Re-deriving that from
memory next month is how runs end up subtly different from each other, so the
definition is stored under the session and can also be exported as a file the
user keeps.

**Uploaded files are deliberately not part of a saved pipeline.** A parameter
like ``primer_file`` holds the id of an upload, and that upload is deleted when
retention runs out; a saved pipeline that quietly pointed at a missing file
would fail at launch with an id nobody can interpret. Those parameters are
stripped on save and listed in ``requires_uploads`` instead, so re-running asks
for the primer FASTA again by name and by the step that needs it.

What *is* kept is the identity of the file that was used: when a parameter
named one of the session's own uploads at save time, its entry carries
``used_file`` = {name, size_bytes, sha256}. A re-run can then be checked
against the exact primer set or reference of the original, and the software
versions the definition was saved under travel with it (``software``). The
upload's server-side id never leaves the server.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.config import MAX_SAVED_PIPELINES, SAVED_PIPELINE_TTL, redis_client
from app.core.file_store import get_file
from app.core.provenance import file_fingerprint, software_versions
from app.pipeline.contracts import STEP_CONTRACTS
from app.pipeline.planner import UPLOAD_PARAM_KEYS

#: Bumped when the exported document's shape changes incompatibly.
EXPORT_FORMAT = "airr-preprocessor.pipeline"
EXPORT_VERSION = 1


@dataclass
class SavedPipeline:
    pipeline_id: str
    session_id: str
    name: str
    chains: int
    steps: list[dict]
    description: str = ""
    #: [{step_index, step_name, param}] -- uploads the run will ask for again.
    requires_uploads: list[dict] = field(default_factory=list)
    #: Where it came from, when saved straight off a finished run.
    source_job_id: Optional[str] = None
    #: provenance.software_versions() at save time.
    software: dict = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _key(session_id: str, pipeline_id: str) -> str:
    return f"session:{session_id}:pipeline:{pipeline_id}"


def _index_key(session_id: str) -> str:
    return f"session:{session_id}:pipelines"


def _fingerprint_upload(file_id: Any, owned_file_ids: set[str]) -> dict | None:
    """Content identity of an upload this session owns, or None."""
    if not isinstance(file_id, str) or file_id not in owned_file_ids:
        return None
    stored = get_file(file_id)
    if stored is None:
        return None
    try:
        return file_fingerprint(stored.path, name=stored.original_name)
    except OSError:
        return None


def strip_upload_params(
    steps: list[dict],
    owned_file_ids: set[str] | None = None,
    known_files: dict[tuple[int, str], dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Remove upload references from a pipeline and report what was removed.

    Returns (steps without file ids,
             [{step_index, step_name, param, required, used_file?}]).

    ``used_file`` is filled from ``owned_file_ids`` (a save: only this
    session's own uploads are fingerprinted, so a foreign id reveals nothing)
    or carried over from ``known_files`` (an import of an exported document).
    """
    cleaned: list[dict] = []
    required: list[dict] = []
    owned_file_ids = owned_file_ids or set()
    known_files = known_files or {}

    for index, step in enumerate(steps or []):
        name = step.get("name", "")
        params = dict(step.get("params") or {})
        contract_files = set(STEP_CONTRACTS.get(name, {}).get("requires_files", []))

        for key in list(params):
            if key in UPLOAD_PARAM_KEYS or key in contract_files:
                value = params.pop(key, None)
                entry = {
                    "step_index": index,
                    "step_name": name,
                    "param": key,
                    "required": key in contract_files,
                }
                used = _fingerprint_upload(value, owned_file_ids) or known_files.get(
                    (index, key)
                )
                if used:
                    entry["used_file"] = used
                required.append(entry)

        entry = {"name": name, "params": params}
        if step.get("id"):
            entry["id"] = step["id"]
        if step.get("lanes"):
            entry["lanes"] = step["lanes"]
        cleaned.append(entry)

    return cleaned, required


def save_pipeline(
    session_id: str,
    name: str,
    chains: int,
    steps: list[dict],
    description: str = "",
    source_job_id: str | None = None,
    pipeline_id: str | None = None,
    owned_file_ids: set[str] | None = None,
    known_files: dict[tuple[int, str], dict] | None = None,
) -> SavedPipeline:
    """Store (or overwrite) one pipeline definition under this session."""
    cleaned, required = strip_upload_params(steps, owned_file_ids, known_files)
    now = time.time()

    existing = get_pipeline(session_id, pipeline_id) if pipeline_id else None
    record = SavedPipeline(
        pipeline_id=pipeline_id or str(uuid.uuid4()),
        session_id=session_id,
        name=name.strip() or "Untitled pipeline",
        description=description.strip(),
        chains=int(chains),
        steps=cleaned,
        requires_uploads=required,
        source_job_id=source_job_id,
        software=software_versions(),
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )

    redis_client.set(
        _key(session_id, record.pipeline_id),
        json.dumps(record.to_dict()),
        ex=SAVED_PIPELINE_TTL,
    )
    _index_add(session_id, record.pipeline_id)
    return record


def _index_add(session_id: str, pipeline_id: str) -> None:
    ids = _index_read(session_id)
    ids = [i for i in ids if i != pipeline_id]
    ids.insert(0, pipeline_id)
    # Oldest saves fall off rather than letting one session grow without bound.
    for stale in ids[MAX_SAVED_PIPELINES:]:
        redis_client.delete(_key(session_id, stale))
    _index_write(session_id, ids[:MAX_SAVED_PIPELINES])


def _index_read(session_id: str) -> list[str]:
    raw = redis_client.get(_index_key(session_id))
    return json.loads(raw) if raw else []


def _index_write(session_id: str, ids: list[str]) -> None:
    redis_client.set(_index_key(session_id), json.dumps(ids), ex=SAVED_PIPELINE_TTL)


def get_pipeline(session_id: str, pipeline_id: str) -> Optional[SavedPipeline]:
    raw = redis_client.get(_key(session_id, pipeline_id))
    if not raw:
        return None
    data = json.loads(raw)
    known = set(SavedPipeline.__dataclass_fields__)
    return SavedPipeline(**{k: v for k, v in data.items() if k in known})


def list_pipelines(session_id: str) -> list[SavedPipeline]:
    """Saved pipelines for this session, newest save first."""
    found = []
    live_ids = []
    for pipeline_id in _index_read(session_id):
        record = get_pipeline(session_id, pipeline_id)
        if record:
            found.append(record)
            live_ids.append(pipeline_id)
    # Drop index entries whose record expired, so the list stays honest.
    if len(live_ids) != len(_index_read(session_id)):
        _index_write(session_id, live_ids)
    found.sort(key=lambda p: p.updated_at, reverse=True)
    return found


def delete_pipeline(session_id: str, pipeline_id: str) -> bool:
    removed = redis_client.delete(_key(session_id, pipeline_id)) > 0
    _index_write(
        session_id, [i for i in _index_read(session_id) if i != pipeline_id]
    )
    return removed


def to_export_document(record: SavedPipeline) -> dict[str, Any]:
    """
    The portable form: a plain JSON document with no session or file ids in it.

    Keeping it free of server-side identifiers is what lets the same file be
    imported into another session, another browser, or a colleague's account
    and still describe the same workflow.
    """
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "name": record.name,
        "description": record.description,
        "chains": record.chains,
        "steps": record.steps,
        "requires_uploads": record.requires_uploads,
        # Versions the workflow was saved under, and those exporting it now.
        "software": record.software or None,
        "exported_by": software_versions(),
        "exported_at": time.time(),
    }


class PipelineImportError(ValueError):
    """The supplied document is not a pipeline this app can run."""


def from_export_document(document: Any) -> dict[str, Any]:
    """
    Validate an imported document and return {name, description, chains, steps}.

    Strict about shape but forgiving about provenance: a document saved by an
    older version, or hand-edited, is accepted as long as every step names a
    component this server actually has.
    """
    if not isinstance(document, dict):
        raise PipelineImportError("Expected a JSON object describing a pipeline")

    fmt = document.get("format")
    if fmt is not None and fmt != EXPORT_FORMAT:
        raise PipelineImportError(
            f"Unrecognised pipeline format '{fmt}'. Expected '{EXPORT_FORMAT}'."
        )

    version = document.get("version", EXPORT_VERSION)
    if not isinstance(version, int) or version > EXPORT_VERSION:
        raise PipelineImportError(
            f"This file was written by a newer version (v{version}); "
            f"this server understands up to v{EXPORT_VERSION}."
        )

    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PipelineImportError("The pipeline has no steps")

    chains = document.get("chains", 1)
    if chains not in (1, 2):
        raise PipelineImportError("chains must be 1 (single-read) or 2 (paired-end)")

    steps: list[dict] = []
    for index, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            raise PipelineImportError(f"Step {index + 1} is not an object")
        name = step.get("name")
        if not name or name not in STEP_CONTRACTS:
            raise PipelineImportError(
                f"Step {index + 1} names an unknown component: {name!r}"
            )
        params = step.get("params") or {}
        if not isinstance(params, dict):
            raise PipelineImportError(f"Step {index + 1} has invalid parameters")

        entry = {"id": step.get("id") or f"s{index + 1}", "name": name, "params": params}
        lanes = step.get("lanes")
        if lanes:
            entry["lanes"] = lanes
        steps.append(entry)

    # Recomputed rather than trusted from the file, so a hand-edited document
    # cannot smuggle a file id past the strip. The recorded identity of each
    # file used originally is carried over, but only in its expected shape.
    steps, required = strip_upload_params(steps, known_files=known_files_from_document(document))

    return {
        "name": str(document.get("name") or "Imported pipeline")[:120],
        "description": str(document.get("description") or "")[:500],
        "chains": chains,
        "steps": steps,
        "requires_uploads": required,
    }


def known_files_from_document(document: dict) -> dict[tuple[int, str], dict]:
    """(step_index, param) -> used_file, from an exported document."""
    found: dict[tuple[int, str], dict] = {}
    for entry in document.get("requires_uploads") or []:
        if not isinstance(entry, dict):
            continue
        used = entry.get("used_file")
        index, param = entry.get("step_index"), entry.get("param")
        if not (isinstance(used, dict) and isinstance(index, int) and isinstance(param, str)):
            continue
        name, size, digest = used.get("name"), used.get("size_bytes"), used.get("sha256")
        if (
            isinstance(name, str)
            and isinstance(size, int)
            and isinstance(digest, str)
            and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest)
        ):
            found[(index, param)] = {"name": name[:255], "size_bytes": size, "sha256": digest}
    return found
