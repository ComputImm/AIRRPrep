"""
Job-time pipeline validation.

Uses STEP_CONTRACTS + step_parameter_analyzer (analyze_parameter_effects /
capabilities_after_step) through planner.apply_step.
"""

from pathlib import Path

from app.pipeline.contracts import STEP_CONTRACTS
from app.pipeline.file_inspector import format_from_suffix
from app.pipeline.planner import (
    PlannerError,
    PlannerState,
    apply_step,
    compose_summary,
    initial_planner_state,
    initial_planner_state_from_paths,
)
from app.pipeline.registry import PIPELINE_FUNCTIONS
from app.pipeline.step_parameter_analyzer import (
    analyze_parameter_effects,
    capabilities_after_step,
    fields_satisfy_contract,
    step_satisfies_contract,
)
from app.pipeline.stream import (
    LANE_R1,
    LANE_R2,
    StepStreamBehavior,
    StreamMode,
    get_step_stream_behavior,
    normalize_step_lanes,
)


class PipelineValidationError(Exception):
    pass


def validate(steps: list[dict]) -> bool:
    for step in steps:
        if step["name"] not in PIPELINE_FUNCTIONS:
            raise PipelineValidationError(f"Invalid step: {step['name']}")
    return True


def validate_stream_transitions(steps: list[dict], num_input_files: int) -> None:
    if num_input_files not in (1, 2):
        raise PipelineValidationError(
            f"Expected 1 or 2 input files, got {num_input_files}"
        )

    mode = StreamMode.DUAL if num_input_files == 2 else StreamMode.SINGLE

    for step in steps:
        step_name = step["name"]
        behavior = get_step_stream_behavior(step_name)

        if behavior in (
            StepStreamBehavior.PAIRED_IO,
            StepStreamBehavior.MERGE_PAIRED,
        ):
            if mode != StreamMode.DUAL:
                raise PipelineValidationError(
                    f"{step_name} requires two input files (R1 and R2)"
                )

        if behavior == StepStreamBehavior.MERGE_PAIRED:
            mode = StreamMode.SINGLE
        elif behavior == StepStreamBehavior.PAIRED_IO:
            mode = StreamMode.DUAL

        if behavior == StepStreamBehavior.PER_LANE:
            try:
                target_lanes = normalize_step_lanes(step, mode)
            except ValueError as e:
                raise PipelineValidationError(str(e)) from e

            if LANE_R2 in target_lanes and num_input_files < 2:
                raise PipelineValidationError(
                    f"{step_name} targets R2 but only one input file was provided"
                )


def _target_lanes(step: dict, stream_mode: StreamMode) -> list[str]:
    behavior = get_step_stream_behavior(step["name"])
    if behavior in (StepStreamBehavior.PAIRED_IO, StepStreamBehavior.MERGE_PAIRED):
        return [LANE_R1, LANE_R2]
    return normalize_step_lanes(step, stream_mode)


def validate_steps_with_parameter_effects(
    chains: int,
    input_format: str,
    steps: list[dict],
    initial_state: PlannerState | None = None,
) -> PlannerState:
    """
    For each step:
      - check contract (requires / requires_any / input_types) on target lanes
      - compute capabilities_after_step via analyze_parameter_effects
      - apply_step updates stream state

    initial_state lets the caller seed lane capabilities detected from the real
    input files; without it only the declared format is known.
    """
    state = initial_state or initial_planner_state(chains, input_format)

    for index, step in enumerate(steps):
        step_name = step["name"]
        params = step.get("params") or {}
        label = f"Step {index + 1} ({step_name})"

        if step_name not in STEP_CONTRACTS:
            raise PipelineValidationError(f"{label}: unknown step")

        for lane in _target_lanes(step, state.stream_mode):
            if lane not in state.lanes:
                raise PipelineValidationError(f"{label}: lane {lane} not active")

            lane_state = state.lanes[lane]
            err = step_satisfies_contract(
                step_name,
                lane_state.capabilities,
                lane_state.file_type,
            )
            if err:
                raise PipelineValidationError(f"{label} on {lane}: {err}")

            # Explicit parameter_effects check (same logic apply_step uses)
            analyze_parameter_effects(step_name, params, lane_state.capabilities)
            capabilities_after_step(step_name, params, lane_state.capabilities)

            # Field-name existence check: does a param like SplitSeq's
            # `field` or ParseHeaders' `fields` actually name a field this
            # lane has at this point in the pipeline? Skipped per-lane
            # whenever that lane's registry isn't confident (see
            # LaneState.fields_confident) -- an unconfirmed registry must
            # never reject a value we simply don't know is wrong.
            lane_fields = {
                ln: (ls.fields, ls.fields_confident) for ln, ls in state.lanes.items()
            }
            field_err = fields_satisfy_contract(step_name, params, lane_fields, lane)
            if field_err:
                raise PipelineValidationError(f"{label} on {lane}: {field_err}")

        try:
            state = apply_step(state, step)
        except PlannerError as e:
            raise PipelineValidationError(f"{label}: {e}") from e

    return state


def validate_pipeline(steps: list[dict], file_paths: list[str] | str):
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    if not steps:
        raise PipelineValidationError("Pipeline is empty")

    for file_path in file_paths:
        if not Path(file_path).exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")

    validate(steps)
    validate_stream_transitions(steps, len(file_paths))

    try:
        file_type = format_from_suffix(file_paths[0])
    except ValueError as e:
        raise PipelineValidationError(str(e)) from e

    for path in file_paths[1:]:
        if format_from_suffix(path) != file_type:
            raise PipelineValidationError(
                "All input files must share the same format (by extension)"
            )

    chains = len(file_paths)

    # Seed the lane state from the real files so job-time validation sees the
    # same annotations (BARCODE, UMI, PRIMER, …) the pipeline builder saw when
    # the user assembled the pipeline.
    try:
        initial_state = initial_planner_state_from_paths(chains, file_paths)
    except PlannerError:
        initial_state = None

    try:
        validate_steps_with_parameter_effects(
            chains, file_type, steps, initial_state=initial_state
        )
        summary = compose_summary(
            chains, steps, file_paths=file_paths, input_format=file_type
        )
    except PlannerError as e:
        raise PipelineValidationError(str(e)) from e

    if summary["missing_required_uploads"]:
        missing = ", ".join(
            f"{m['step_name']}.{m['param']}"
            for m in summary["missing_required_uploads"]
        )
        raise PipelineValidationError(f"Missing required uploads: {missing}")

    return True, steps, summary
