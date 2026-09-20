"""
Stateless pipeline planner for the custom UI.

Uses STEP_CONTRACTS + Capability. Initial lane state may come from
declared format only, or from uploaded R1/R2 files (header annotations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.pipeline.capabilities import (
    Capability,
    capability_for_annotation_field,
)
from app.pipeline.contracts import STEP_CONTRACTS
from app.pipeline.registry import PIPELINE_FUNCTIONS
from app.pipeline.splitting import (
    split_reason,
    step_splits_output,
    terminal_message,
)
from app.pipeline.step_parameter_analyzer import capabilities_after_step, fields_after_step
from app.pipeline.stream import (
    LANE_R1,
    LANE_R2,
    StreamMode,
    StepStreamBehavior,
    get_step_stream_behavior,
    normalize_step_lanes,
)

UPLOAD_PARAM_KEYS = frozenset(
    {"primer_file", "ref_file", "value_file", "offset_file"}
)
SEQUENCE_TYPES = frozenset({"fasta", "fastq"})


class PlannerError(Exception):
    pass


@dataclass
class LaneState:
    capabilities: set[Capability] = field(default_factory=set)
    file_type: str = "fastq"
    #: Concrete annotation field names known to exist in this lane right now
    #: (e.g. BARCODE, PRIMER) -- the field-name analogue of `capabilities`.
    fields: set[str] = field(default_factory=set)
    #: False when `fields` may be incomplete (an unrecognized/unconverted
    #: header format) -- see app/pipeline/file_inspector.py:inspect_headers.
    #: Field-existence checks must not enforce against `fields` while this
    #: is False.
    fields_confident: bool = False

    def copy(self) -> "LaneState":
        return LaneState(
            capabilities=set(self.capabilities),
            file_type=self.file_type,
            fields=set(self.fields),
            fields_confident=self.fields_confident,
        )


@dataclass
class PlannerState:
    stream_mode: StreamMode
    lanes: dict[str, LaneState] = field(default_factory=dict)
    #: Set once a step has fanned the lane out into several files (see
    #: app/pipeline/splitting.py). Nothing may follow such a step, so this
    #: holds its name purely to explain why the pipeline stops here.
    terminated_by: str | None = None

    def copy(self) -> "PlannerState":
        return PlannerState(
            stream_mode=self.stream_mode,
            lanes={lane: ls.copy() for lane, ls in self.lanes.items()},
            terminated_by=self.terminated_by,
        )


def chains_to_stream_mode(chains: int | str) -> StreamMode:
    if isinstance(chains, str):
        key = chains.strip().lower()
        if key in ("1", "single", "one"):
            return StreamMode.SINGLE
        if key in ("2", "dual", "two", "pair"):
            return StreamMode.DUAL
        raise PlannerError(f"Unknown chains value: {chains}")
    if chains == 1:
        return StreamMode.SINGLE
    if chains == 2:
        return StreamMode.DUAL
    raise PlannerError("chains must be 1 or 2")


def _state_from_lane_files(
    mode: StreamMode,
    lane_files: list[tuple[str, str, str, set[Capability], set[str], bool]],
) -> PlannerState:
    """
    Assemble a PlannerState from (lane, path, file_type, extra_caps,
    extra_fields, extra_confident) tuples.
    """
    from app.pipeline.file_inspector import inspect_headers

    lanes: dict[str, LaneState] = {}
    file_types: list[str] = []

    for lane, path, file_type, extra_caps, extra_fields, extra_confident in lane_files:
        if not Path(path).exists():
            raise PlannerError(f"File missing on disk: {path}")
        if file_type == "unknown":
            raise PlannerError(f"Cannot detect format for file {path}")

        caps, fields, confident = inspect_headers(path)
        caps |= set(extra_caps)
        fields |= set(extra_fields)
        confident = confident or extra_confident
        lanes[lane] = LaneState(
            capabilities=caps, file_type=file_type, fields=fields, fields_confident=confident
        )
        file_types.append(file_type)

    if len(set(file_types)) > 1:
        got = {lane: file_type for lane, _, file_type, _, _, _ in lane_files}
        raise PlannerError(
            f"R1 and R2 must share the same format, got: {got}"
        )

    if mode == StreamMode.DUAL:
        lanes[LANE_R1].capabilities.add(Capability.PAIRED_END)
        lanes[LANE_R2].capabilities.add(Capability.PAIRED_END)

    return PlannerState(stream_mode=mode, lanes=lanes)


def _lane_order(mode: StreamMode) -> list[str]:
    return [LANE_R1] if mode == StreamMode.SINGLE else [LANE_R1, LANE_R2]


def initial_planner_state_from_paths(
    chains: int | str,
    file_paths: list[str],
) -> PlannerState:
    """
    Build planner state from files already on disk (job launch time).

    Uses the same header-based capability detection as the upload path, so a
    pipeline the builder accepted still validates when the job is launched —
    otherwise any step that requires a barcode/UMI would be rejected at launch
    just because the declared format alone carries no annotations.
    """
    from app.pipeline.file_inspector import detect_file_type

    mode = chains_to_stream_mode(chains)
    expected = 1 if mode == StreamMode.SINGLE else 2

    if len(file_paths) != expected:
        raise PlannerError(
            f"chains={expected} requires {expected} file(s), got {len(file_paths)}"
        )

    lane_files = [
        (lane, path, detect_file_type(path), set(), set(), False)
        for lane, path in zip(_lane_order(mode), file_paths)
    ]
    return _state_from_lane_files(mode, lane_files)


def initial_planner_state_from_file_ids(
    chains: int | str,
    file_ids: list[str],
) -> PlannerState:
    """
    Build planner state from uploaded files.

    chains=1 → exactly one file_id (R1).
    chains=2 → two file_ids: [R1, R2].
    Capabilities are detected from sequence headers at upload / init time.
    """
    from app.core.file_store import get_file

    mode = chains_to_stream_mode(chains)
    expected = 1 if mode == StreamMode.SINGLE else 2

    if len(file_ids) != expected:
        raise PlannerError(
            f"chains={expected} requires {expected} file_id(s), got {len(file_ids)}"
        )

    lane_files = []
    for lane, file_id in zip(_lane_order(mode), file_ids):
        stored = get_file(file_id)
        if not stored:
            raise PlannerError(f"Uploaded file not found: {file_id}")

        extra: set[Capability] = set()
        for cap_name in stored.capabilities:
            try:
                extra.add(Capability(cap_name))
            except ValueError:
                pass

        extra_fields = {str(f).strip().upper() for f in (stored.fields or [])}
        lane_files.append(
            (lane, stored.path, stored.file_type, extra, extra_fields, stored.fields_confident)
        )

    return _state_from_lane_files(mode, lane_files)


def resolve_planner_state(
    chains: int | str,
    steps: list[dict] | None = None,
    *,
    file_ids: list[str] | None = None,
    file_paths: list[str] | None = None,
    input_format: str = "fastq",
) -> PlannerState:
    """Initial state from files (preferred) or declared format, then apply steps."""
    if file_ids:
        state = initial_planner_state_from_file_ids(chains, file_ids)
    elif file_paths:
        state = initial_planner_state_from_paths(chains, file_paths)
    else:
        state = initial_planner_state(chains, input_format)

    for step in steps or []:
        state = apply_step(state, step)
    return state


def initial_planner_state(chains: int | str, input_format: str = "fastq") -> PlannerState:
    fmt = str(input_format).lower()
    if fmt not in SEQUENCE_TYPES:
        raise PlannerError(f"input_format must be fasta or fastq, got {fmt}")

    mode = chains_to_stream_mode(chains)
    caps: set[Capability] = set()
    if fmt == "fastq":
        caps.add(Capability.QUALITY)

    lanes = {LANE_R1: LaneState(capabilities=caps.copy(), file_type=fmt)}
    if mode == StreamMode.DUAL:
        lanes[LANE_R2] = LaneState(capabilities=caps.copy(), file_type=fmt)
        lanes[LANE_R1].capabilities.add(Capability.PAIRED_END)
        lanes[LANE_R2].capabilities.add(Capability.PAIRED_END)
    # No real file to inspect here -- fields stay empty/unconfident (LaneState
    # defaults), same as the declared-format-only path always meant "nothing
    # about annotations is known" for capabilities.

    return PlannerState(stream_mode=mode, lanes=lanes)


def _resolve_output_type(contract: dict, current_type: str) -> str:
    out = contract.get("output_type", "same")
    return current_type if out == "same" else out


def _caps_list(caps: set[Capability]) -> list[str]:
    return sorted(c.value for c in caps)


def _fields_list(fields: set[str]) -> list[str]:
    return sorted(fields)


def _contract_caps(contract: dict, key: str) -> list[str]:
    return _caps_list(set(contract.get(key, [])))


def lane_passes_contract(lane_state: LaneState, contract: dict) -> str | None:
    if lane_state.file_type not in contract.get("input_types", []):
        return (
            f"file type '{lane_state.file_type}' not in "
            f"{contract.get('input_types', [])}"
        )
    caps = lane_state.capabilities
    required = set(contract.get("requires", []))
    missing = required - caps
    if missing:
        return f"missing {_caps_list(missing)}"
    required_any = set(contract.get("requires_any", []))
    if required_any and not required_any.intersection(caps):
        return f"needs one of {_caps_list(required_any)}"
    return None


def lanes_valid_for_step(
    state: PlannerState,
    step_name: str,
    params: dict | None = None,
) -> list[str]:
    """Lanes where this step may run according to the contract (empty = not valid)."""
    contract = STEP_CONTRACTS[step_name]
    behavior = get_step_stream_behavior(step_name)

    if behavior in (StepStreamBehavior.PAIRED_IO, StepStreamBehavior.MERGE_PAIRED):
        if state.stream_mode != StreamMode.DUAL:
            return []
        for lane in (LANE_R1, LANE_R2):
            if lane_passes_contract(state.lanes[lane], contract):
                return []
        return [LANE_R1, LANE_R2]

    allowed = []
    for lane in state.lanes:
        lane_state = state.lanes[lane]
        if params and step_name.startswith("ParseHeaders."):
            from app.pipeline.parse_headers_effects import (
                apply_parse_headers_capability_changes,
            )

            probe_caps = apply_parse_headers_capability_changes(
                step_name, params, lane_state.capabilities
            )
            probe = LaneState(capabilities=probe_caps, file_type=lane_state.file_type)
            if lane_passes_contract(probe, contract) is not None:
                continue
        elif lane_passes_contract(lane_state, contract) is not None:
            continue
        allowed.append(lane)
    return allowed


def _apply_pairseq_field_copy(params: dict, lanes: dict[str, LaneState]) -> None:
    fields_1 = params.get("fields_1") or []
    fields_2 = params.get("fields_2") or []

    for field in fields_1:
        cap = capability_for_annotation_field(field)
        if cap and cap in lanes[LANE_R1].capabilities:
            lanes[LANE_R2].capabilities.add(cap)

    for field in fields_2:
        cap = capability_for_annotation_field(field)
        if cap and cap in lanes[LANE_R2].capabilities:
            lanes[LANE_R1].capabilities.add(cap)


def _apply_pairseq_field_registry_copy(params: dict, lanes: dict[str, LaneState]) -> None:
    """Field-registry analogue of _apply_pairseq_field_copy above."""
    fields_1 = [str(f).strip().upper() for f in (params.get("fields_1") or [])]
    fields_2 = [str(f).strip().upper() for f in (params.get("fields_2") or [])]

    for name in fields_1:
        if name in lanes[LANE_R1].fields:
            lanes[LANE_R2].fields.add(name)

    for name in fields_2:
        if name in lanes[LANE_R2].fields:
            lanes[LANE_R1].fields.add(name)


def apply_step(state: PlannerState, step: dict) -> PlannerState:
    step_name = step["name"]
    if step_name not in STEP_CONTRACTS:
        raise PlannerError(f"Unknown step: {step_name}")

    params = step.get("params") or {}
    contract = STEP_CONTRACTS[step_name]
    behavior = get_step_stream_behavior(step_name)

    if state.terminated_by:
        raise PlannerError(
            f"{step_name} cannot follow {state.terminated_by}: "
            + terminal_message(state.terminated_by)
        )

    splits = step_splits_output(step_name, params)
    state = state.copy()

    if behavior == StepStreamBehavior.MERGE_PAIRED:
        if state.stream_mode != StreamMode.DUAL:
            raise PlannerError(f"{step_name} requires R1 and R2")
        for lane in (LANE_R1, LANE_R2):
            err = lane_passes_contract(state.lanes[lane], contract)
            if err:
                raise PlannerError(f"{step_name} on {lane}: {err}")

        merged = state.lanes[LANE_R1].capabilities | state.lanes[LANE_R2].capabilities
        merged |= set(contract.get("produces", []))
        merged_fields = state.lanes[LANE_R1].fields | state.lanes[LANE_R2].fields
        merged_fields |= set(contract.get("produces_fields", []))
        # Conservative: only trust the merged registry once both sides do --
        # an assembled read's header could otherwise silently drop whichever
        # side's annotations we weren't sure about.
        merged_confident = (
            state.lanes[LANE_R1].fields_confident and state.lanes[LANE_R2].fields_confident
        )
        out_type = _resolve_output_type(contract, state.lanes[LANE_R1].file_type)
        return PlannerState(
            stream_mode=StreamMode.SINGLE,
            lanes={
                LANE_R1: LaneState(
                    capabilities=merged,
                    file_type=out_type,
                    fields=merged_fields,
                    fields_confident=merged_confident,
                )
            },
        )

    if behavior == StepStreamBehavior.PAIRED_IO:
        if state.stream_mode != StreamMode.DUAL:
            raise PlannerError(f"{step_name} requires R1 and R2")
        for lane in (LANE_R1, LANE_R2):
            err = lane_passes_contract(state.lanes[lane], contract)
            if err:
                raise PlannerError(f"{step_name} on {lane}: {err}")

        _apply_pairseq_field_copy(params, state.lanes)
        _apply_pairseq_field_registry_copy(params, state.lanes)
        out_type = _resolve_output_type(contract, state.lanes[LANE_R1].file_type)
        for lane in (LANE_R1, LANE_R2):
            state.lanes[lane].file_type = out_type
        if splits:
            state.terminated_by = step_name
        return state

    target_lanes = normalize_step_lanes(step, state.stream_mode)
    for lane in target_lanes:
        if lane not in state.lanes:
            raise PlannerError(f"{step_name}: lane {lane} not active")

        err = lane_passes_contract(state.lanes[lane], contract)
        if err:
            raise PlannerError(f"{step_name} on {lane}: {err}")

        lane_state = state.lanes[lane]
        caps = capabilities_after_step(
            step_name, params, lane_state.capabilities
        )
        fields, fields_confident = fields_after_step(
            step_name, params, lane_state.fields, lane_state.fields_confident
        )
        state.lanes[lane] = LaneState(
            capabilities=caps,
            file_type=_resolve_output_type(contract, lane_state.file_type),
            fields=fields,
            fields_confident=fields_confident,
        )

    if splits:
        state.terminated_by = step_name

    return state


def simulate_pipeline(
    chains: int | str,
    steps: list[dict],
    *,
    file_ids: list[str] | None = None,
    file_paths: list[str] | None = None,
    input_format: str = "fastq",
) -> PlannerState:
    return resolve_planner_state(
        chains,
        steps,
        file_ids=file_ids,
        file_paths=file_paths,
        input_format=input_format,
    )


def get_valid_next_steps(state: PlannerState) -> list[dict[str, Any]]:
    """
    Steps that satisfy the contract on at least one lane (or both for paired steps).
    Output fields come straight from contracts.py.
    """
    out: list[dict[str, Any]] = []

    # A split ends the run: the lane is now N files, not one stream.
    if state.terminated_by:
        return out

    for step_name in sorted(PIPELINE_FUNCTIONS.keys()):
        if step_name not in STEP_CONTRACTS:
            continue

        contract = STEP_CONTRACTS[step_name]

        if any(ls.file_type == "tab" for ls in state.lanes.values()):
            if contract.get("output_type") != "tab":
                continue

        allowed_lanes = lanes_valid_for_step(state, step_name)
        if not allowed_lanes:
            continue

        out.append({
            "step": step_name,
            "allowed_lanes": allowed_lanes,
            "requires_capabilities": _contract_caps(contract, "requires"),
            "requires_any_capabilities": _contract_caps(contract, "requires_any"),
            "produces_capabilities": _contract_caps(contract, "produces"),
            "requires_files": list(contract.get("requires_files", [])),
            "requires_executable": list(contract.get("requires_executable", [])),
            "input_types": list(contract.get("input_types", [])),
            "output_type": contract.get("output_type", "same"),
            "stream_behavior": get_step_stream_behavior(step_name).value,
            # "always" / "conditional" / None — the UI warns before the user
            # picks a step that will end their pipeline.
            "splits_output": contract.get("splits_output"),
        })

    return out


def explain_step_fit(
    state: PlannerState,
    step_name: str,
    params: dict | None = None,
    lanes: str | list[str] | None = None,
) -> tuple[bool, str | None, list[str]]:
    """Full check with params (for check-step / draft)."""
    if step_name not in STEP_CONTRACTS:
        return False, f"Unknown step: {step_name}", []

    step = {"name": step_name, "params": params or {}}
    if lanes is not None:
        step["lanes"] = lanes

    target_lanes = normalize_step_lanes(step, state.stream_mode)
    allowed = []
    for lane in target_lanes:
        if lane not in state.lanes:
            continue
        if lane_passes_contract(state.lanes[lane], STEP_CONTRACTS[step_name]) is None:
            allowed.append(lane)

    if not allowed:
        return False, f"{step_name}: no lane satisfies contract", []

    try:
        apply_step(state, step)
    except PlannerError as e:
        return False, str(e), allowed

    return True, None, allowed


def collect_required_uploads(steps: list[dict]) -> list[dict[str, Any]]:
    uploads = []
    for index, step in enumerate(steps):
        step_name = step.get("name", "")
        contract = STEP_CONTRACTS.get(step_name, {})
        params = step.get("params") or {}

        for key in contract.get("requires_files", []):
            uploads.append({
                "step_index": index,
                "step_id": step.get("id"),
                "step_name": step_name,
                "param": key,
                "required": True,
                "provided": bool(params.get(key)),
            })

        for key in UPLOAD_PARAM_KEYS:
            if key in contract.get("requires_files", []):
                continue
            if params.get(key):
                uploads.append({
                    "step_index": index,
                    "step_id": step.get("id"),
                    "step_name": step_name,
                    "param": key,
                    "required": False,
                    "provided": True,
                    "lanes": step.get("lanes"),
                })

    return uploads


def compose_summary(
    chains: int | str,
    steps: list[dict],
    *,
    file_ids: list[str] | None = None,
    file_paths: list[str] | None = None,
    input_format: str = "fastq",
) -> dict[str, Any]:
    state = simulate_pipeline(
        chains,
        steps,
        file_ids=file_ids,
        file_paths=file_paths,
        input_format=input_format,
    )
    uploads = collect_required_uploads(steps)
    missing = [u for u in uploads if u.get("required") and not u.get("provided")]

    fmt = input_format
    if state.lanes:
        fmt = next(iter(state.lanes.values())).file_type

    # A splitting last step is fine (it is what the user asked for); a
    # splitting step anywhere else already raised in apply_step.
    splitting_step = next(
        (
            s
            for s in steps
            if step_splits_output(s.get("name", ""), s.get("params") or {})
        ),
        None,
    )

    return {
        "valid": len(missing) == 0,
        "chains": 2 if chains_to_stream_mode(chains) == StreamMode.DUAL else 1,
        "input_format": fmt,
        "sequence_inputs": {
            "count": 2 if chains_to_stream_mode(chains) == StreamMode.DUAL else 1,
            "format": fmt,
            "file_ids": file_ids or [],
        },
        "final_stream": state.stream_mode.value,
        "lane_file_types": {lane: ls.file_type for lane, ls in state.lanes.items()},
        "lane_capabilities": {
            lane: _caps_list(ls.capabilities) for lane, ls in state.lanes.items()
        },
        "lane_fields": {
            lane: _fields_list(ls.fields) for lane, ls in state.lanes.items()
        },
        "lane_fields_confident": {
            lane: ls.fields_confident for lane, ls in state.lanes.items()
        },
        "required_uploads": uploads,
        "missing_required_uploads": missing,
        # Present when the run ends in a fan-out: the UI tells the user to
        # expect a set of part files rather than one final output.
        "terminated_by": state.terminated_by,
        "split_reason": (
            split_reason(
                splitting_step["name"], splitting_step.get("params") or {}
            )
            if splitting_step
            else None
        ),
    }
