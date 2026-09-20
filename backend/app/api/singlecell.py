# app/api/singlecell.py
"""
Single-cell preprocessing API.

Reuses the existing session/upload/job/download infrastructure end to end —
see app/api/sessions.py for uploads, main.py for job-status polling and the
generic path-based job download route. Only three new endpoints are needed:
detect, validate, and jobs/start.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import (
    TRUST4_BARCODE_WHITELIST,
    TRUST4_BIN,
    TRUST4_DEFAULT_SPECIES,
    TRUST4_SPECIES_REFS,
    TRUST4_THREADS,
)
from app.core.file_store import get_file
from app.core.auth import verify_session_token
from app.core.estimate import estimate_singlecell_job
from app.core.job_notifications import (
    JobNotificationRequired,
    attach_job_notification,
)
from app.core.job_workspace import JobWorkspace
from app.core.security import validate_identifier
from app.core.job_store import get_job, update_job
from app.services import session_service
from app.services.job_service import create_job
from app.singlecell.detector import detect_adapter, get_format_spec
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import (
    CHEMISTRY_PRESETS,
    TRUST4_ASSEMBLY_FORMATS,
    DetectionResult,
    Trust4ChemistryInfo,
    Trust4Options,
    Trust4SpeciesInfo,
    Trust4Status,
)
from app.singlecell.registry import AdapterContext, get_adapter
from app.singlecell.trust4_runner import Trust4Runner
from app.singlecell.tasks import process_single_cell_input

logger = logging.getLogger("app")

router = APIRouter(prefix="/singlecell", tags=["singlecell"])


class SingleCellFilesRequest(BaseModel):
    session_id: str
    file_ids: list[str] = Field(..., min_length=1)


class SingleCellValidateRequest(SingleCellFilesRequest):
    format_id: str
    #: Only read for the raw-read formats; ignored for assembled input.
    trust4_options: Trust4Options | None = None
    #: Opt-in for carrying Cell Ranger's annotation-derived `productive` call
    #: through to the output. Null unless explicitly requested.
    allow_productive: bool = False
    #: Generic FASTA only: regex with one capture group, applied to the FASTA
    #: header to recover the cell barcode when no mapping file is uploaded.
    barcode_header_regex: str | None = None
    #: Frontend page this run was launched from, and a human name for it, so
    #: a tracking-code recovery lands the user back on the same page.
    route: str | None = None
    label: str | None = None
    #: role -> file_id. Sent by the per-workflow pages, where the user picked
    #: the format up front and dropped each file into a named slot, so the
    #: assignment is already known and must not be re-guessed from filenames.
    #: Absent for the detect-driven flow, which falls back to name matching.
    role_file_ids: dict[str, str] | None = None


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    record_count_estimate: int | None = None


class StartJobResponse(BaseModel):
    session_id: str
    job_id: str
    format_id: str
    #: Set only when the session has a verified email address; see
    #: app/core/job_notifications.py.
    tracking_code: str | None = None


def _resolve_stored_files(session_id: str, file_ids: list[str]):
    session_id = validate_identifier(session_id, "session_id")
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stored_files = []
    for file_id in file_ids:
        stored = get_file(file_id)
        if not stored:
            raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        stored_files.append(stored)
    return stored_files


def _role_paths_for_format(stored_files, format_id: str) -> dict[str, Path]:
    """Re-run detection against the given file set and pick out the file
    paths for the roles the chosen format_id's spec expects."""
    spec = get_format_spec(format_id)
    role_paths: dict[str, Path] = {}
    for role in spec.roles:
        for stored in stored_files:
            if role.matches(stored.original_name):
                role_paths[role.name] = Path(stored.path)
                break
    return role_paths


def _role_names(stored_files, role_paths: dict[str, Path]) -> dict[str, str]:
    """Original upload filename per role, for the job's provenance record."""
    by_path = {Path(f.path).resolve(): f.original_name for f in stored_files}
    return {
        role: by_path.get(Path(path).resolve(), Path(path).name)
        for role, path in role_paths.items()
    }


def _resolve_role_paths(
    stored_files, format_id: str, role_file_ids: dict[str, str] | None
) -> dict[str, Path]:
    """Use the client's explicit role assignment when it sent one, otherwise
    fall back to matching filenames against the format spec.

    The explicit path is what makes the per-workflow pages work: a file
    dropped into the "contig FASTA" slot is that role regardless of whether
    its name happens to contain "all_contig".
    """
    if not role_file_ids:
        return _role_paths_for_format(stored_files, format_id)

    valid_roles = {role.name for role in get_format_spec(format_id).roles}
    by_id = {stored.file_id: stored for stored in stored_files}

    role_paths: dict[str, Path] = {}
    for role, file_id in role_file_ids.items():
        if role not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role {role!r} for format {format_id!r}",
            )
        stored = by_id.get(file_id)
        if stored is None:
            raise HTTPException(
                status_code=400,
                detail=f"Role {role!r} references file {file_id!r}, "
                       "which is not in file_ids",
            )
        role_paths[role] = Path(stored.path)
    return role_paths


def _trust4_status() -> Trust4Status:
    """Whether raw-read (FASTQ/BAM) input can be assembled on this server."""
    species: list[Trust4SpeciesInfo] = []
    binary_problems: list[str] = []

    for species_id, refs in TRUST4_SPECIES_REFS.items():
        try:
            runner = Trust4Runner(species=species_id)
        except Exception as e:  # unusable species config — report, don't crash
            species.append(
                Trust4SpeciesInfo(
                    id=species_id, label=refs["label"], available=False,
                    problems=[str(e)],
                )
            )
            continue
        binary_problems = runner.check_binary()
        ref_problems = runner.check_references()
        species.append(
            Trust4SpeciesInfo(
                id=species_id,
                label=refs["label"],
                available=not binary_problems and not ref_problems,
                problems=ref_problems,
            )
        )

    return Trust4Status(
        available=any(s.available for s in species),
        binary=TRUST4_BIN,
        problems=binary_problems,
        species=species,
        chemistries=[
            Trust4ChemistryInfo(
                id=cid,
                label=preset["label"],
                barcode_range=preset["barcode_range"],
                umi_range=preset["umi_range"],
            )
            for cid, preset in CHEMISTRY_PRESETS.items()
        ],
        default_species=TRUST4_DEFAULT_SPECIES,
        threads=TRUST4_THREADS,
        barcode_whitelist_configured=bool(TRUST4_BARCODE_WHITELIST),
    )


@router.get("/trust4/status", response_model=Trust4Status)
async def singlecell_trust4_status():
    return _trust4_status()


@router.post("/detect", response_model=DetectionResult)
async def singlecell_detect(body: SingleCellFilesRequest):
    try:
        stored_files = _resolve_stored_files(body.session_id, body.file_ids)
        return detect_adapter(
            stored_files, trust4_available=_trust4_status().available
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/validate", response_model=ValidateResponse)
async def singlecell_validate(body: SingleCellValidateRequest):
    try:
        stored_files = _resolve_stored_files(body.session_id, body.file_ids)
        role_paths = _resolve_role_paths(
            stored_files, body.format_id, body.role_file_ids
        )

        # No work_dir: adapter.validate() must never assemble, so nothing here
        # has anywhere to write. See FastqAdapter.validate.
        adapter = get_adapter(
            body.format_id,
            AdapterContext(
                trust4_options=body.trust4_options,
                allow_productive=body.allow_productive,
                barcode_header_regex=body.barcode_header_regex,
            ),
        )
        count, warnings = adapter.validate(role_paths)

        return ValidateResponse(
            valid=True, warnings=warnings, record_count_estimate=count
        )
    except SingleCellAdapterError as e:
        return ValidateResponse(valid=False, errors=[str(e)])
    except HTTPException:
        raise
    except ValueError as e:
        return ValidateResponse(valid=False, errors=[str(e)])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/jobs/start", response_model=StartJobResponse)
async def singlecell_start_job(
    body: SingleCellValidateRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    validate_identifier(body.session_id, "session_id")
    if not verify_session_token(body.session_id, x_session_token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")

    # Fail fast on a raw-read format the server can't assemble, rather than
    # queueing a job that is certain to fail minutes later.
    options = body.trust4_options or Trust4Options()
    if body.format_id in TRUST4_ASSEMBLY_FORMATS:
        problems = Trust4Runner(species=options.species).check_available()
        if problems:
            raise HTTPException(status_code=400, detail="; ".join(problems))

    # One active job per session, same rule as the bulk pipeline
    # (main.py::_find_active_job) — reimplemented locally rather than
    # importing from main.py to avoid a circular import (main.py includes
    # this router).
    try:
        existing_job_ids = session_service.get_session_jobs(body.session_id)
    except ValueError:
        existing_job_ids = []
    for jid in existing_job_ids:
        job = get_job(body.session_id, jid)
        status = str(job.get("status") or "") if job else ""
        if status in ("", "PENDING") or status.startswith("PROCESSING"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "A job is already running for this session. "
                    "Wait for it to finish before starting a new one."
                ),
            )

    job_id = create_job(file_path="", session_id=body.session_id, steps=[])
    try:
        session_service.add_job_to_session(body.session_id, job_id)
    except ValueError:
        pass

    def _fail_job(message: str):
        try:
            update_job(body.session_id, job_id, {"status": "FAILED", "error": message})
        except Exception:
            pass

    try:
        stored_files = _resolve_stored_files(body.session_id, body.file_ids)
        role_paths = _resolve_role_paths(
            stored_files, body.format_id, body.role_file_ids
        )
        if not role_paths:
            _fail_job("None of the uploaded files matched the selected format")
            raise HTTPException(
                status_code=400,
                detail="None of the uploaded files matched the selected format",
            )

        workspace = JobWorkspace(session_id=body.session_id, job_id=job_id)
        workspace.create()

        update_job(body.session_id, job_id, {
            "session_id": body.session_id,
            "module": "single_cell",
            "format_id": body.format_id,
            "file_ids": body.file_ids,
        })

        # Raw-read formats route through TRUST4 and run for hours, so these
        # are always gated; assembled input is sized on the uploads alone.
        # Same server-side enforcement as the bulk endpoint in main.py.
        estimate = estimate_singlecell_job(
            [str(path) for path in role_paths.values()],
            needs_assembly=body.format_id in TRUST4_ASSEMBLY_FORMATS,
        )
        try:
            tracking_code = attach_job_notification(
                session_id=body.session_id,
                job_id=job_id,
                estimate=estimate,
                route=body.route or f"/single-cell/{body.format_id}",
                label=body.label or "single-cell preprocessing",
            )
        except JobNotificationRequired as e:
            _fail_job("Email verification required")
            raise HTTPException(
                status_code=428,
                detail={
                    "error": "email_verification_required",
                    "message": (
                        "This run needs a verified email address before it can "
                        "start."
                    ),
                    "estimate": e.estimate.to_dict(),
                },
            )

        process_single_cell_input.delay(
            {role: str(path) for role, path in role_paths.items()},
            str(workspace.outputs_path),
            job_id,
            body.session_id,
            body.format_id,
            options.model_dump() if body.format_id in TRUST4_ASSEMBLY_FORMATS else None,
            body.allow_productive,
            body.barcode_header_regex,
            _role_names(stored_files, role_paths),
        )

        return StartJobResponse(
            session_id=body.session_id,
            job_id=job_id,
            format_id=body.format_id,
            tracking_code=tracking_code,
        )
    except HTTPException:
        raise
    except Exception as e:
        _fail_job(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start job: {e}") from e
