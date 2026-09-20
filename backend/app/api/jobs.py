import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.job_store import get_job, request_cancel, update_job
from app.core.job_workspace import JobWorkspace
from app.core.auth import require_session_token
from app.core.security import validate_identifier


router = APIRouter()


def _load_job(session_id: str, job_id: str) -> dict:
    try:
        job = get_job(session_id, job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read job: {e}")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _step_entry(job: dict, index: int) -> dict:
    entry = next(
        (s for s in job.get("step_stats", []) if s.get("index") == index),
        None,
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Step not found")
    return entry


@router.get("/sessions/{session_id}/jobs/{job_id}/download")
def download_job_output(
    session_id: str,
    job_id: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")
    try:
        workspace = JobWorkspace(session_id, job_id)

        output_files = sorted(
            p for p in workspace.outputs_path.glob("*")
            if p.is_file() and not p.stem.endswith("_fail")
        )

        if not output_files:
            # A run that ended in a fan-out has no single final output -- the
            # parts are the result. Say so rather than a bare "not found".
            job = get_job(session_id, job_id) or {}
            if job.get("ends_in_split"):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "This run ends in a split, so it has no single final "
                        "output. Download the individual parts, or use "
                        "download-all to get them as one archive."
                    ),
                )
            raise HTTPException(status_code=404, detail="No output found")

        file_path = output_files[0]

        return FileResponse(
            path=file_path,
            filename=file_path.name
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


@router.get("/sessions/{session_id}/jobs/{job_id}/steps/{index}/download")
def download_step_file(
    session_id: str,
    job_id: str,
    index: int,
    kind: str = Query("pass"),
    lane: str | None = Query(None),
    part: str | None = Query(
        None,
        description=(
            "Label of one part written by a splitting step (e.g. 'part3', "
            "'atleast-2'). Takes precedence over kind/lane."
        ),
    ),
    _: str = Depends(require_session_token),
):
    """
    Download one file written by a single pipeline step.

    Step file paths are read from the job's ``step_stats`` (populated by the
    executor). The fail file is either an explicit ``*_fail`` entry in
    ``output_paths`` or the sibling ``{stem}_fail{suffix}`` written by the
    pRESTO wrappers (MaskPrimers, AssemblePairs, ...). Steps that do not emit
    a fail file (FilterSeq with nothing filtered, ParseHeaders.table, which
    writes a TSV and has no pass/fail split at all) return 404 for
    ``kind=fail``.

    A splitting step (SplitSeq.count, SplitSeq.group without a threshold, ...)
    wrote several files instead of one; ``part`` names which of them to send.
    """
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")
    job = _load_job(session_id, job_id)

    if kind not in ("pass", "fail"):
        raise HTTPException(status_code=400, detail="kind must be 'pass' or 'fail'")

    try:
        entry = _step_entry(job, index)

        if part:
            match = next(
                (p for p in entry.get("parts") or [] if p.get("label") == part),
                None,
            )
            if not match:
                raise HTTPException(
                    status_code=404, detail=f"No part '{part}' for step {index}"
                )
            target = match.get("path")
        else:
            output_paths = entry.get("output_paths") or {}
            pass_lanes = [k for k in output_paths if not k.endswith("_fail")]

            if lane and lane in output_paths:
                chosen = lane
            elif pass_lanes:
                chosen = pass_lanes[0]
            else:
                raise HTTPException(status_code=404, detail="No output for this step")

            if kind == "fail":
                target = (
                    output_paths.get(f"{chosen}_fail")
                    or output_paths.get("merged_fail")
                )
                if not target:
                    pass_path = Path(output_paths[chosen])
                    target = str(
                        pass_path.with_name(f"{pass_path.stem}_fail{pass_path.suffix}")
                    )
            else:
                target = output_paths.get(chosen)

        if not target or not Path(target).is_file():
            raise HTTPException(
                status_code=404,
                detail=f"No {part or kind} file available for step {index}",
            )

        target_path = Path(target)
        return FileResponse(path=target_path, filename=target_path.name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")


@router.get("/sessions/{session_id}/jobs/{job_id}/download-all")
def download_all_job_files(
    session_id: str,
    job_id: str,
    scope: str = Query(
        "outputs",
        description=(
            "'outputs' zips every file the pipeline produced (per-step results "
            "and the final output); 'all' also includes the uploaded inputs."
        ),
    ),
    _: str = Depends(require_session_token),
):
    """
    One archive holding every file this run produced.

    Entries keep the names they have on disk -- dataset, tracking code, step
    number and step name -- inside ``steps/`` and ``outputs/`` folders, so an
    unzipped run reads in pipeline order without opening a single file.
    """
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")

    if scope not in ("outputs", "all"):
        raise HTTPException(status_code=400, detail="scope must be 'outputs' or 'all'")

    job = _load_job(session_id, job_id)
    workspace = JobWorkspace(session_id, job_id)

    if not workspace.base_path.exists():
        raise HTTPException(status_code=404, detail="Job workspace not found")

    sections = ["steps", "outputs"] if scope == "outputs" else ["input", "steps", "outputs"]
    entries = [
        f
        for f in workspace.get_all_files()
        if f["section"] in sections
    ]
    if not entries:
        raise HTTPException(status_code=404, detail="This run has no files yet")

    stem = job.get("run_prefix") or job_id
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        with ZipFile(temp_zip.name, "w", compression=ZIP_DEFLATED) as archive:
            for info in entries:
                archive.write(
                    workspace.base_path / info["relative_path"],
                    arcname=f"{stem}/{info['relative_path']}",
                )
    finally:
        temp_zip.close()

    suffix = "all_files" if scope == "all" else "results"
    return FileResponse(
        path=temp_zip.name,
        filename=f"{stem}_{suffix}.zip",
        media_type="application/zip",
    )


@router.post("/sessions/{session_id}/jobs/{job_id}/cancel")
def cancel_job(
    session_id: str,
    job_id: str,
    _: str = Depends(require_session_token),
):
    """
    Stop a running job.

    The worker checks between steps, so a job stops once the step in flight
    finishes rather than mid-write -- everything completed up to that point
    stays on disk and downloadable. A job that has not been picked up yet is
    revoked outright so it never starts.
    """
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")
    job = _load_job(session_id, job_id)

    status = str(job.get("status") or "")
    if status == "DONE" or status.startswith(("FAILED", "Fail ", "CANCELLED")):
        raise HTTPException(
            status_code=409, detail="This job has already finished"
        )

    request_cancel(session_id, job_id)

    task_id = job.get("celery_task_id")
    if task_id:
        try:
            from app.workers.celery_worker import celery

            # Not terminate=True: killing the worker mid-step would leave a
            # half-written file behind and take any other task sharing the
            # process with it. A queued task is dropped, a running one stops
            # at its next step boundary.
            celery.control.revoke(task_id)
        except Exception:
            # Losing the broker still leaves the Redis flag, which is what the
            # running worker actually reads.
            pass

    # `status` belongs to whoever is running the job. Writing it from here
    # races the worker: a run that finishes in the moment between this read and
    # this write ends up stuck showing "STOPPING" forever, because the worker's
    # DONE was overwritten. So a started job gets only the `cancel_requested`
    # flag, and the worker writes CANCELLED when it acts on it.
    #
    # A job still queued is different -- revoke() means no worker will ever
    # touch it, so nothing is going to write a final status but us.
    started = status.startswith("PROCESSING") or status.startswith("DONE ")
    update: dict = {"cancel_requested": True}
    if started:
        message = "The run will stop after the step currently in progress."
    else:
        update["status"] = "CANCELLED before it started"
        update["cancelled"] = True
        message = "The run was cancelled before it started."

    update_job(session_id, job_id, update)
    return {
        "job_id": job_id,
        "cancel_requested": True,
        "status": update.get("status", status),
        "message": message,
    }
