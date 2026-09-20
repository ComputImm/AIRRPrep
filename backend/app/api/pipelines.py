"""
Saving, exporting and importing pipeline definitions.

A pipeline the user assembled is worth keeping: it is the part of a run that
took thought, and re-running the same workflow on next month's samples should
not mean rebuilding it from memory. Two ways out are offered, and they are the
same document underneath:

* saved to the session, listed in the builder, one click to load; and
* exported as a JSON file the user keeps, which imports into any session.

Uploads never travel with a pipeline (see app/core/pipeline_store.py), so the
responses always say which steps will ask for a file again.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Literal

from app.core.auth import require_session_token
from app.core.pipeline_store import (
    PipelineImportError,
    delete_pipeline,
    from_export_document,
    known_files_from_document,
    get_pipeline,
    list_pipelines,
    save_pipeline,
    to_export_document,
)
from app.core.security import validate_identifier
from app.core.naming import sanitize_token
from app.pipeline.parser import parse_steps
from app.pipeline.planner import PlannerError, compose_summary
from app.services import session_service

router = APIRouter(tags=["pipelines"])


class PipelineStepInput(BaseModel):
    id: str | None = None
    name: str
    params: dict = Field(default_factory=dict)
    lanes: str | list[str] | None = None


class SavePipelineBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    chains: Literal[1, 2] = 1
    steps: list[PipelineStepInput] = Field(..., min_length=1)
    source_job_id: str | None = None
    #: Set to overwrite an existing saved pipeline instead of adding one.
    pipeline_id: str | None = None


class ImportPipelineBody(BaseModel):
    #: The parsed contents of an exported .json file.
    document: Any


def _owned_file_ids(session_id: str) -> set[str]:
    try:
        return set(session_service.get_session_files(session_id))
    except ValueError:
        return set()


def _require_session(session_id: str):
    session = session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _serialize(record) -> dict:
    data = record.to_dict()
    data["step_count"] = len(record.steps)
    return data


@router.post("/sessions/{session_id}/pipelines")
async def create_saved_pipeline(
    session_id: str,
    body: SavePipelineBody,
    _: str = Depends(require_session_token),
):
    """Save a pipeline definition so it can be loaded and run again."""
    session_id = validate_identifier(session_id, "session_id")
    _require_session(session_id)

    steps = [s.model_dump(exclude_none=True) for s in body.steps]
    record = save_pipeline(
        session_id=session_id,
        name=body.name,
        chains=body.chains,
        steps=steps,
        description=body.description,
        source_job_id=body.source_job_id,
        pipeline_id=body.pipeline_id,
        owned_file_ids=_owned_file_ids(session_id),
    )
    return _serialize(record)


@router.get("/sessions/{session_id}/pipelines")
async def list_saved_pipelines(
    session_id: str,
    _: str = Depends(require_session_token),
):
    """Every pipeline saved in this session, most recently updated first."""
    session_id = validate_identifier(session_id, "session_id")
    _require_session(session_id)
    return {
        "session_id": session_id,
        "pipelines": [_serialize(p) for p in list_pipelines(session_id)],
    }


@router.get("/sessions/{session_id}/pipelines/{pipeline_id}")
async def read_saved_pipeline(
    session_id: str,
    pipeline_id: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    pipeline_id = validate_identifier(pipeline_id, "pipeline_id")
    record = get_pipeline(session_id, pipeline_id)
    if not record:
        raise HTTPException(status_code=404, detail="Saved pipeline not found")
    return _serialize(record)


@router.get("/sessions/{session_id}/pipelines/{pipeline_id}/export")
async def export_saved_pipeline(
    session_id: str,
    pipeline_id: str,
    _: str = Depends(require_session_token),
):
    """
    The pipeline as a downloadable JSON file.

    Sent with a Content-Disposition filename so the browser saves it under the
    pipeline's own name; the body is the same document the import endpoint
    accepts.
    """
    session_id = validate_identifier(session_id, "session_id")
    pipeline_id = validate_identifier(pipeline_id, "pipeline_id")
    record = get_pipeline(session_id, pipeline_id)
    if not record:
        raise HTTPException(status_code=404, detail="Saved pipeline not found")

    document = to_export_document(record)
    filename = f"{sanitize_token(record.name, 'pipeline')}.pipeline.json"
    return JSONResponse(
        content=document,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/sessions/{session_id}/pipelines/{pipeline_id}")
async def remove_saved_pipeline(
    session_id: str,
    pipeline_id: str,
    _: str = Depends(require_session_token),
):
    session_id = validate_identifier(session_id, "session_id")
    pipeline_id = validate_identifier(pipeline_id, "pipeline_id")
    if not delete_pipeline(session_id, pipeline_id):
        raise HTTPException(status_code=404, detail="Saved pipeline not found")
    return {"pipeline_id": pipeline_id, "deleted": True}


@router.post("/sessions/{session_id}/pipelines/import")
async def import_pipeline(
    session_id: str,
    body: ImportPipelineBody,
    save: bool = Query(
        False, description="Also store the imported pipeline in this session."
    ),
    _: str = Depends(require_session_token),
):
    """
    Read an exported pipeline file back into a runnable step list.

    The document is checked against this server's component catalog before it
    is handed to the builder, so a file from an older release fails here with a
    sentence naming the offending step rather than deep inside a run.
    """
    session_id = validate_identifier(session_id, "session_id")
    _require_session(session_id)

    document = body.document
    # Accept the file's raw text as well as parsed JSON: a paste-into-a-box
    # flow never gets to parse it first.
    if isinstance(document, str):
        try:
            document = json.loads(document)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400, detail=f"That is not valid JSON: {e.msg}"
            ) from e

    try:
        imported = from_export_document(document)
    except PipelineImportError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    saved = None
    if save:
        record = save_pipeline(
            session_id=session_id,
            name=imported["name"],
            chains=imported["chains"],
            steps=imported["steps"],
            description=imported["description"],
            known_files=known_files_from_document(document),
        )
        saved = _serialize(record)

    return {**imported, "saved": saved}


@router.post("/sessions/{session_id}/pipelines/preview")
async def preview_pipeline(
    session_id: str,
    body: SavePipelineBody,
    _: str = Depends(require_session_token),
):
    """
    Dry-run a saved or imported pipeline against nothing but the contracts.

    Used before offering "run this again": it catches a workflow that can no
    longer be executed (a component removed, a step order that no longer
    validates) without asking the user to upload their reads first.
    """
    session_id = validate_identifier(session_id, "session_id")
    _require_session(session_id)

    steps = parse_steps([s.model_dump(exclude_none=True) for s in body.steps])
    fmt = "fastq"
    try:
        summary = compose_summary(body.chains, steps, input_format=fmt)
    except PlannerError as e:
        # Reported rather than raised: the pipeline may still be fine once real
        # files supply the annotations the contracts are asking for.
        return {"runnable": False, "error": str(e), "steps": steps}

    return {"runnable": True, "summary": summary, "steps": steps}
