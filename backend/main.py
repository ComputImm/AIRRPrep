from app.workers.celery_worker import process_file
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, Depends, Header
import tempfile 
from zipfile import ZipFile,ZIP_DEFLATED
import aiofiles
from pathlib import Path
from app.services.job_service import create_job
from app.services.session_service import add_job_to_session, get_session_jobs
from app.core.job_store import get_job, update_job
from app.core.job_workspace import JobWorkspace
from app.core.security import (
    MAX_UPLOAD_SIZE_BYTES,
    resolve_within,
    safe_filename,
    validate_identifier,
    validate_upload_extension,
)
from app.core.auth import require_session_token, verify_session_token
from app.core.naming import dataset_label_for_inputs, run_prefix
from app.pipeline.parser import parse_steps
from app.pipeline.validator import PipelineValidationError, validate_pipeline
from app.pipeline.metadata import (
    get_step_metadata,
    get_all_steps_metadata,
)
from fastapi.responses import FileResponse, JSONResponse
from app.api import sessions
from app.api.pipeline_builder import router as pipeline_builder_router
from app.api.jobs import router as jobs_router
from app.api.pipelines import router as pipelines_router
from app.api.notifications import router as notifications_router
from app.api.singlecell import router as singlecell_router
from app.core.job_notifications import (
    JobNotificationRequired,
    attach_job_notification,
)
from app.core.estimate import estimate_bulk_job
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from app.config import ALLOWED_ORIGINS
from app.core.rate_limit import limiter, rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging

logger = logging.getLogger("app")

app = FastAPI()

# --- Rate limiting -----------------------------------------------------
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(sessions.router, prefix="/api", tags=["sessions"])
app.include_router(pipeline_builder_router, prefix="/api")
app.include_router(pipelines_router, prefix="/api")
app.include_router(singlecell_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
# Step file downloads live at the application root (e.g. /sessions/{sid}/jobs/{jid}/...)
app.include_router(jobs_router, tags=["jobs"])

# --- CORS ---------------------------------------------------------------
# Origins are read from the ALLOWED_ORIGINS env var (comma separated).
# No cookies/auth headers are used by this API, so credentials stay off —
# that also means allow_origins can never resolve to "*" unsafely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Session-Token"],
)


# --- Security headers -----------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# --- Request size guard ----------------------------------------------------
# File uploads stream and enforce their own limit as they read; this catches
# oversized *non-file* bodies (JSON payloads etc.) via Content-Length before
# they're read into memory at all.
_MAX_JSON_BODY_BYTES = 5 * 1024 * 1024  # 5 MB


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > _MAX_JSON_BODY_BYTES:
                return JSONResponse(
                    status_code=413, content={"detail": "Request body too large"}
                )
    return await call_next(request)


class PipelineStep(BaseModel):
    id: str
    name: str
    params: dict = Field(default_factory=dict)
    # "R1" | "R2" | "both" — omitted means both lanes when two inputs exist
    lanes: str | list[str] | None = None

class StartJobRequest(BaseModel):
    session_id: str
    file_ids: list[str]  # ✅ لیست فایل‌هایی که کاربر آپلود کرده
    steps: list[PipelineStep]
    convert_to_fasta: bool = False
    # Frontend page this run was launched from, and a human name for it.
    # Stored with the tracking code so returning via a tracking code puts the
    # user back on the same page rather than a generic results screen.
    route: str | None = None
    label: str | None = None

@app.get("/")
async def root():
    return {"message": "running"}

@app.post("/upload")
@limiter.limit("10/minute")
async def upload(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    session_id = validate_identifier(session_id, "session_id")
    if not verify_session_token(session_id, x_session_token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    suffix = validate_upload_extension(file.filename)

    # ساخت job
    job_id = create_job(
        session_id=session_id,
        file_path="",
        steps=[]
    )

    # ساخت workspace session-aware
    workspace = JobWorkspace(
        session_id=session_id,
        job_id=job_id
    )

    workspace.create()

    file_path = (
        workspace.upload_dir /
        f"input{suffix}"
    )

    size = 0
    async with aiofiles.open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE_BYTES:
                await f.close()
                file_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="File too large")
            await f.write(chunk)

    job_data = get_job(session_id, job_id)

    job_data["file_path"] = str(file_path)

    update_job(
        session_id,
        job_id,
        job_data
    )

    return {
        "session_id": session_id,
        "job_id": job_id,
        "file_path": str(file_path)

}

@app.get("/sessions/{session_id}/jobs/{job_id}")
def job_status(session_id: str, job_id: str, _: str = Depends(require_session_token)):
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")
    try:
        job_data = get_job(session_id, job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read job: {e}")

    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    return job_data

@app.get("/jobs/{session_id}/{job_id}/download-all")
@limiter.limit("20/minute")
async def download_all_files(
    request: Request,
    session_id: str,
    job_id: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")

    workspace = JobWorkspace(
        session_id=session_id,
        job_id=job_id
    )

    if not workspace.base_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    files = workspace.get_all_files()
    temp_zip = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".zip"
    )

    with ZipFile(temp_zip.name, "w", compression=ZIP_DEFLATED) as zipf:

        for file_info in files:

            full_path = workspace.base_path / file_info["relative_path"]

            zipf.write(
                full_path,
                arcname=file_info["relative_path"]
            )

    job = get_job(session_id, job_id) or {}
    stem = job.get("run_prefix") or job_id

    return FileResponse(
        path=temp_zip.name,
        filename=f"{stem}_all_files.zip",
        media_type="application/zip"
    )


@app.get("/jobs/{session_id}/{job_id}/files")
async def list_job_files(
    session_id: str,
    job_id: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")

    workspace = JobWorkspace(
        session_id=session_id,
        job_id=job_id
    )

    if not workspace.base_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return {
        "files": workspace.get_all_files()
    }

@app.get("/jobs/{session_id}/{job_id}/download")
@limiter.limit("30/minute")
async def download_file(
    request: Request,
    session_id: str,
    job_id: str,
    path: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    job_id = validate_identifier(job_id, "job_id")

    workspace = JobWorkspace(
        session_id=session_id,
        job_id=job_id
    )

    if not workspace.base_path.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    # `path` is user-controlled — resolve_within() rejects any "../" or
    # absolute-path attempt to escape the job's own workspace directory.
    file_path = resolve_within(workspace.base_path, path)

    if not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="File not found"
        )

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream"
    )

def _is_active_status(status) -> bool:
    """Whether a job is still queued or running (not in a terminal state)."""
    if not status:
        # A freshly created job with no status yet counts as active.
        return True
    status = str(status)
    if (
        status == "DONE"
        or status.startswith("FAILED")
        or status.startswith("Fail ")
        or status.startswith("CANCELLED")
    ):
        return False
    # A run the user asked to stop is on its way out; it must not keep the
    # session locked against starting the next one.
    if "| STOPPING" in status:
        return False
    return status == "PENDING" or status.startswith("PROCESSING")


def _find_active_job(session_id: str):
    """Return the id of an in-flight job for this session, or None."""
    try:
        job_ids = get_session_jobs(session_id)
    except ValueError:
        return None
    except Exception:
        return None
    for jid in job_ids:
        try:
            job = get_job(session_id, jid)
        except Exception:
            continue
        if job and _is_active_status(job.get("status")):
            return jid
    return None


@app.post("/jobs/start")
@limiter.limit("10/minute")
async def start_pipeline(
    request: Request,
    body: StartJobRequest,
    x_session_token: str | None = Header(default=None, alias="X-Session-Token"),
):
    validate_identifier(body.session_id, "session_id")
    if not verify_session_token(body.session_id, x_session_token):
        raise HTTPException(status_code=403, detail="Invalid or missing session token")
    if not body.file_ids:
        raise HTTPException(status_code=400, detail="No files provided")

    # ✅ هر session فقط یک job در حال اجرا داشته باشد
    active = _find_active_job(body.session_id)
    if active:
        raise HTTPException(
            status_code=409,
            detail=(
                "A job is already running for this session. "
                "Wait for it to finish before starting a new one."
            ),
        )

    # ✅ ساخت job جدید
    job_id = create_job(
        session_id=body.session_id,
        file_path="",  # بعداً پر می‌شه
        steps=body.steps
    )

    # ✅ ثبت job در session تا در تاریخچه (history) دیده شود
    try:
        add_job_to_session(body.session_id, job_id)
    except ValueError:
        pass

    def _fail_job(message: str):
        """Mark the just-created job FAILED so it does not linger as active."""
        try:
            update_job(body.session_id, job_id, {"status": "FAILED", "error": message})
        except Exception:
            pass

    try:
        workspace = JobWorkspace(
            session_id=body.session_id,
            job_id=job_id
        )
        workspace.create()
        steps = [step.model_dump() for step in body.steps]

        # ✅ پیدا کردن فایل‌های آپلود شده از file_store
        from app.core.file_store import get_file
        file_paths = []
        original_names = []
        for file_id in body.file_ids:
            stored_file = get_file(file_id)
            if not stored_file:
                _fail_job(f"File {file_id} not found")
                raise HTTPException(status_code=404, detail=f"File {file_id} not found")
            file_paths.append(str(stored_file.path))
            original_names.append(stored_file.original_name)

        # Every file this run writes is named after the dataset it came from,
        # so a downloads folder holding several runs still makes sense.
        dataset = dataset_label_for_inputs(original_names)

        file_suffix = Path(file_paths[0]).suffix.lower()
        steps = parse_steps(steps)

        try:
            _, steps, summary = validate_pipeline(steps, file_paths)
        except PipelineValidationError as e:
            _fail_job(str(e))
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            _fail_job(str(e))
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError as e:
            _fail_job(str(e))
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            _fail_job(str(e))
            raise HTTPException(status_code=500, detail=str(e))

        output_file = (
            workspace.outputs_path /
            f"final{file_suffix}"
        )
        job_data = get_job(body.session_id, job_id)
        job_data["file_paths"] = file_paths
        job_data["file_path"] = file_paths[0]
        job_data["input_names"] = original_names
        job_data["dataset"] = dataset
        job_data["pipeline_summary"] = summary
        update_job(body.session_id, job_id, job_data)

        # Long runs need a verified email before they may start. Re-estimated
        # here rather than trusted from the client: /api/jobs/estimate is what
        # the UI asks so it can open the dialog, this is what enforces it.
        estimate = estimate_bulk_job(file_paths, steps)
        try:
            tracking_code = attach_job_notification(
                session_id=body.session_id,
                job_id=job_id,
                estimate=estimate,
                route=body.route or "/bulk",
                label=body.label or "bulk preprocessing",
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

        # The tracking code is the string the user was emailed and the one
        # they will search their downloads for, so it goes in the file names.
        # Untracked runs fall back to the short job id the UI already shows.
        stem = run_prefix(dataset, job_id, tracking_code)

        task = process_file.delay(
            file_paths,
            str(output_file),
            job_id,
            steps,
            body.session_id,
            body.convert_to_fasta,
            stem,
        )

        # Recorded so the cancel endpoint can revoke a job that has not been
        # picked up by a worker yet (once it is running, the worker stops at
        # the next step boundary instead).
        update_job(
            body.session_id,
            job_id,
            {"celery_task_id": task.id, "run_prefix": stem},
        )

        return {
            "session_id": body.session_id,
            "job_id": job_id,  # ✅ job_id جدید ساخته شده
            "steps": body.steps,
            "lane_capabilities": summary["lane_capabilities"],
            "lane_file_types": summary["lane_file_types"],
            "run_prefix": stem,
            # Present only when the session has a verified email; the UI shows
            # it next to the progress panel so the code is on screen as well
            # as in the inbox.
            "tracking_code": tracking_code,
        }
    except HTTPException:
        raise
    except Exception as e:
        _fail_job(str(e))
        raise HTTPException(status_code=500, detail=f"Failed to start job: {e}")


@app.get("/steps")
async def list_steps():
    try:
        return get_all_steps_metadata()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load steps: {e}")

@app.get("/steps/{step_name}")
async def step_details(step_name: str):
    try:
        return get_step_metadata(step_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
