"""
Custom pipeline builder API.

Flow:
  1. POST /api/sessions/{session_id}/files  — upload R1 (and R2 if chains=2)
  2. POST /api/pipeline/custom/init         — file_ids + chains → valid first steps
  3. POST /api/pipeline/custom/next-steps   — steps + file_ids → valid next steps
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.pipeline.metadata import get_step_metadata
from app.pipeline.parser import parse_steps
from app.pipeline.planner import (
    PlannerError,
    compose_summary,
    explain_step_fit,
    get_valid_next_steps,
    initial_planner_state_from_file_ids,
    resolve_planner_state,
)
from app.pipeline.stream import LANE_R1, LANE_R2
from app.pipeline.validator import (
    PipelineValidationError,
    validate_steps_with_parameter_effects,
)

router = APIRouter(prefix="/pipeline/custom", tags=["pipeline-custom"])


class PipelineStepInput(BaseModel):
    id: str | None = None
    name: str
    params: dict = Field(default_factory=dict)
    lanes: str | list[str] | None = None


class CustomInitResponse(BaseModel):
    chains: int
    input_format: str
    stream_mode: str
    lane_file_types: dict[str, str]
    lane_capabilities: dict[str, list[str]]
    #: Concrete annotation field names known to exist in each lane right now
    #: (e.g. BARCODE, PRIMER) -- what the UI offers as dropdown options for a
    #: field-name parameter. See lane_fields_confident.
    lane_fields: dict[str, list[str]]
    #: False when a lane's field list may be incomplete (an unrecognized or
    #: not-yet-normalized header format) -- the UI should still allow a
    #: typed/custom value in that case rather than only the dropdown.
    lane_fields_confident: dict[str, bool]
    lane_file_ids: dict[str, str]
    valid_next_steps: list[dict]
    message: str
    #: Always None here (init has no steps yet); present so the client reads
    #: one response shape from both init and next-steps.
    terminated_by: str | None = None


class CustomPlannerRequest(BaseModel):
    chains: Literal[1, 2]
    file_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=2,
        description="Uploaded file IDs: [R1] or [R1, R2]",
    )
    steps: list[PipelineStepInput] = Field(default_factory=list)
    input_format: Literal["fasta", "fastq"] | None = Field(
        default=None,
        description="Optional override; otherwise taken from uploaded files",
    )

    @field_validator("file_ids")
    @classmethod
    def file_ids_match_chains(cls, file_ids: list[str], info):
        chains = info.data.get("chains")
        if chains == 1 and len(file_ids) != 1:
            raise ValueError("chains=1 requires exactly one file_id (R1)")
        if chains == 2 and len(file_ids) != 2:
            raise ValueError("chains=2 requires two file_ids (R1, R2)")
        return file_ids


class CustomNextStepsRequest(CustomPlannerRequest):
    draft_step: PipelineStepInput | None = None


class CustomCheckStepRequest(CustomPlannerRequest):
    step: PipelineStepInput


def _lane_file_ids(file_ids: list[str], chains: int) -> dict[str, str]:
    if chains == 1:
        return {LANE_R1: file_ids[0]}
    return {LANE_R1: file_ids[0], LANE_R2: file_ids[1]}


def _state_response(state, file_ids: list[str], chains: int) -> dict:
    fmt = next(iter(state.lanes.values())).file_type if state.lanes else "fastq"
    return {
        "stream_mode": state.stream_mode.value,
        "input_format": fmt,
        "lane_file_types": {k: v.file_type for k, v in state.lanes.items()},
        "lane_capabilities": {
            k: sorted(c.value for c in v.capabilities)
            for k, v in state.lanes.items()
        },
        "lane_fields": {k: sorted(v.fields) for k, v in state.lanes.items()},
        "lane_fields_confident": {
            k: v.fields_confident for k, v in state.lanes.items()
        },
        "lane_file_ids": _lane_file_ids(file_ids, chains),
        "valid_next_steps": get_valid_next_steps(state),
        # Set once a step has fanned the lane out into several files, which
        # ends the pipeline (app/pipeline/splitting.py). valid_next_steps is
        # empty in that case, and this is what lets the UI say why rather than
        # leaving every component mysteriously locked.
        "terminated_by": state.terminated_by,
    }


@router.get("/init-options")
async def custom_init_options():
    return {
        "chains": [
            {
                "value": 1,
                "label": "Single chain",
                "description": "Upload one file (R1).",
            },
            {
                "value": 2,
                "label": "Dual chain (R1 + R2)",
                "description": "Upload two files: R1 then R2.",
            },
        ],
        "workflow": [
            "POST /api/sessions — create session",
            "POST /api/sessions/{session_id}/files — upload FASTA/FASTQ (×1 or ×2)",
            "POST /api/pipeline/custom/init — body: { chains, file_ids: [R1] or [R1,R2] }",
            "POST /api/pipeline/custom/next-steps — after each step, send steps + same file_ids",
        ],
        "lane_mapping": {
            "file_ids[0]": "R1",
            "file_ids[1]": "R2 (only when chains=2)",
        },
    }


class CustomInitBody(BaseModel):
    chains: Literal[1, 2]
    file_ids: list[str] = Field(..., min_length=1, max_length=2)

    @field_validator("file_ids")
    @classmethod
    def file_ids_match_chains(cls, file_ids: list[str], info):
        chains = info.data.get("chains")
        if chains == 1 and len(file_ids) != 1:
            raise ValueError("chains=1 requires exactly one file_id (R1)")
        if chains == 2 and len(file_ids) != 2:
            raise ValueError("chains=2 requires two file_ids (R1, R2)")
        return file_ids


@router.post("/init", response_model=CustomInitResponse)
async def custom_init(body: CustomInitBody):
    """After upload: detect annotations from files and return valid first steps."""
    try:
        state = initial_planner_state_from_file_ids(body.chains, body.file_ids)
        fmt = next(iter(state.lanes.values())).file_type
        return CustomInitResponse(
            chains=body.chains,
            input_format=fmt,
            stream_mode=state.stream_mode.value,
            lane_file_types={k: v.file_type for k, v in state.lanes.items()},
            lane_capabilities={
                k: sorted(c.value for c in v.capabilities)
                for k, v in state.lanes.items()
            },
            lane_fields={k: sorted(v.fields) for k, v in state.lanes.items()},
            lane_fields_confident={
                k: v.fields_confident for k, v in state.lanes.items()
            },
            lane_file_ids=_lane_file_ids(body.file_ids, body.chains),
            valid_next_steps=get_valid_next_steps(state),
            message="Capabilities detected from file headers; pick a step from valid_next_steps",
        )
    except PlannerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/next-steps")
async def custom_next_steps(body: CustomNextStepsRequest):
    try:
        steps = parse_steps([s.model_dump(exclude_none=True) for s in body.steps])

        state = resolve_planner_state(
            body.chains,
            steps,
            file_ids=body.file_ids,
            input_format=body.input_format or "fastq",
        )

        if body.draft_step:
            draft = parse_steps([body.draft_step.model_dump(exclude_none=True)])[0]
            ok, err, allowed = explain_step_fit(
                state,
                draft["name"],
                draft.get("params"),
                draft.get("lanes"),
            )
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail={"error": err, "allowed_lanes": allowed},
                )
            state = resolve_planner_state(
                body.chains,
                steps + [draft],
                file_ids=body.file_ids,
                input_format=body.input_format or "fastq",
            )

        return _state_response(state, body.file_ids, body.chains)
    except PlannerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PipelineValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/check-step")
async def custom_check_step(body: CustomCheckStepRequest):
    try:
        steps = parse_steps([s.model_dump(exclude_none=True) for s in body.steps])
        state = resolve_planner_state(
            body.chains,
            steps,
            file_ids=body.file_ids,
            input_format=body.input_format or "fastq",
        )

        step = parse_steps([body.step.model_dump(exclude_none=True)])[0]
        ok, err, allowed = explain_step_fit(
            state,
            step["name"],
            step.get("params"),
            step.get("lanes"),
        )
        if not ok:
            return {"valid": False, "error": err, "allowed_lanes": allowed}

        after = resolve_planner_state(
            body.chains,
            steps + [step],
            file_ids=body.file_ids,
            input_format=body.input_format or "fastq",
        )
        return {
            "valid": True,
            "allowed_lanes": allowed,
            "stream_mode_after": after.stream_mode.value,
            "lane_file_types_after": {
                k: v.file_type for k, v in after.lanes.items()
            },
            "lane_capabilities_after": {
                k: sorted(c.value for c in v.capabilities)
                for k, v in after.lanes.items()
            },
            "lane_fields_after": {
                k: sorted(v.fields) for k, v in after.lanes.items()
            },
            "lane_fields_confident_after": {
                k: v.fields_confident for k, v in after.lanes.items()
            },
        }
    except PlannerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/required-files")
async def custom_required_files(body: CustomPlannerRequest):
    try:
        steps = parse_steps([s.model_dump(exclude_none=True) for s in body.steps])
        summary = compose_summary(
            body.chains,
            steps,
            file_ids=body.file_ids,
            input_format=body.input_format or "fastq",
        )
        return {
            "sequence_inputs": summary["sequence_inputs"],
            "required_uploads": summary["required_uploads"],
            "missing_required_uploads": summary["missing_required_uploads"],
        }
    except PlannerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/validate")
async def custom_validate(body: CustomPlannerRequest):
    try:
        steps = parse_steps([s.model_dump(exclude_none=True) for s in body.steps])

        # simulate_pipeline (what compose_summary uses below) only checks
        # capability contracts -- it stays permissive on field-name params on
        # purpose, because the interactive builder calls it after every single
        # step, before the field registry may be confident yet. This explicit
        # "Validate pipeline" gate is different: the file is already uploaded
        # and every step is already committed, so a field a step's param names
        # (e.g. a SplitSeq `field` baked into a loaded/imported pipeline) can
        # and should be checked against what this file's lanes actually have,
        # the same way job launch (/jobs/start) already does.
        initial_state = initial_planner_state_from_file_ids(body.chains, body.file_ids)
        validate_steps_with_parameter_effects(
            body.chains,
            body.input_format or "fastq",
            steps,
            initial_state=initial_state,
        )

        return compose_summary(
            body.chains,
            steps,
            file_ids=body.file_ids,
            input_format=body.input_format or "fastq",
        )
    except PipelineValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PlannerError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/steps/{step_name}")
async def custom_step_metadata(step_name: str):
    try:
        return get_step_metadata(step_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
