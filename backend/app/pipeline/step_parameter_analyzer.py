"""
How step parameters change capabilities (contracts.parameter_effects + ParseHeaders).
Used by planner and validator — single source of truth.
"""

from app.pipeline.capabilities import (
    Capability,
    capability_for_annotation_field,
)
from app.pipeline.contracts import STEP_CONTRACTS
from app.pipeline.parse_headers_effects import (
    PARSE_HEADERS_FIELD_EFFECTS,
    apply_parse_headers_capability_changes,
    apply_parse_headers_field_changes,
)
from app.pipeline.stream import LANE_R1, LANE_R2


def analyze_parameter_effects(
    step_name: str,
    params: dict,
    current_capabilities: set[Capability],
) -> dict:
    if step_name.startswith("ParseHeaders."):
        after = apply_parse_headers_capability_changes(
            step_name, params, current_capabilities
        )
        return {
            "added": after - current_capabilities,
            "removed": current_capabilities - after,
            "unchanged": current_capabilities & after,
        }

    if step_name not in STEP_CONTRACTS:
        return {
            "added": set(),
            "removed": set(),
            "unchanged": current_capabilities.copy(),
        }

    contract = STEP_CONTRACTS[step_name]
    result = {
        "added": set(contract.get("produces", [])),
        "removed": set(),
        "unchanged": current_capabilities.copy(),
    }

    for param_name, effect_config in contract.get("parameter_effects", {}).items():
        if effect_config.get("type") != "filter_annotation_fields":
            continue

        affects = effect_config.get("affects", [])
        if param_name not in params:
            _apply_filter_annotation_fields(None, affects, result)
            continue

        _apply_filter_annotation_fields(params[param_name], affects, result)

    return result


def _apply_filter_annotation_fields(
    param_value,
    affected_fields: list[str],
    result: dict,
) -> None:
    if not param_value:
        for field in affected_fields:
            cap = capability_for_annotation_field(field)
            if cap and cap in result["unchanged"]:
                result["unchanged"].discard(cap)
                result["removed"].add(cap)
        return

    if isinstance(param_value, list):
        kept = {str(f).upper() for f in param_value}
    else:
        kept = {str(f).upper() for f in str(param_value).split(",") if f.strip()}
        if not kept and param_value:
            kept = {str(param_value).upper()}

    for field in affected_fields:
        cap = capability_for_annotation_field(field)
        if not cap:
            continue
        field_upper = field.upper()
        if field_upper in kept or cap.value.upper() in kept:
            continue
        if cap in result["unchanged"]:
            result["unchanged"].discard(cap)
            result["removed"].add(cap)


def capabilities_after_step(
    step_name: str,
    params: dict,
    before: set[Capability],
) -> set[Capability]:
    if step_name.startswith("ParseHeaders."):
        return apply_parse_headers_capability_changes(step_name, params, before)

    effects = analyze_parameter_effects(step_name, params, before)
    caps = set(effects["unchanged"]) | set(effects["added"])
    caps -= set(effects["removed"])

    if "maskprimer" in step_name.lower() and params.get("barcode"):
        field = str(params.get("barcode_field", "BARCODE")).upper()
        if field == "BARCODE":
            caps.add(Capability.BARCODE)
        elif field in ("UMI", "UID"):
            caps.add(Capability.UMI)

    return caps


def step_satisfies_contract(
    step_name: str,
    lane_capabilities: set[Capability],
    file_type: str,
) -> str | None:
    if step_name not in STEP_CONTRACTS:
        return f"unknown step {step_name}"

    contract = STEP_CONTRACTS[step_name]
    supported = contract.get("input_types", [])

    if file_type not in supported:
        return f"file type '{file_type}' not in {supported}"

    required = set(contract.get("requires", []))
    missing = required - lane_capabilities
    if missing:
        return f"missing {', '.join(c.value for c in sorted(missing, key=lambda x: x.value))}"

    required_any = set(contract.get("requires_any", []))
    if required_any and not required_any.intersection(lane_capabilities):
        need = ", ".join(c.value for c in sorted(required_any, key=lambda x: x.value))
        return f"needs one of: {need}"

    return None


# ---------------------------------------------------------------------------
# Field-name registry (planner.LaneState.fields) -- parallel to the
# capability functions above, but tracking concrete field-name strings. See
# contracts.py's module docstring for the field_effects vocabulary.
# ---------------------------------------------------------------------------

_LANE_ALIASES = {"R1": LANE_R1, "R2": LANE_R2}


def _resolve_lane(lane_key: str | None, params: dict, default_lane: str) -> str:
    """
    Resolve a field_effects "lane" key to the physical lane it means right now.

    "head"/"tail" are AssembleSeq's logical roles, not fixed physical lanes:
    the executor's run_assemble_seq_step swaps which file is head/tail at run
    time based on the step's own `swap_head_tail` param (head=R2/tail=R1 when
    set, instead of the default head=R1/tail=R2). Hardcoding head->R1/tail->R2
    here would validate `head_fields`/`tail_fields` against the wrong lane's
    tracked field registry whenever a pipeline actually uses the swap -- either
    rejecting a value that is valid for the physical file being read, or
    passing one that only happens to also exist on the wrong lane.
    """
    if lane_key == "head" or lane_key == "tail":
        swapped = bool(params.get("swap_head_tail"))
        head_lane = LANE_R2 if swapped else LANE_R1
        tail_lane = LANE_R1 if swapped else LANE_R2
        return head_lane if lane_key == "head" else tail_lane
    return _LANE_ALIASES.get(lane_key, default_lane)


def _field_effects_for(step_name: str) -> dict:
    if step_name.startswith("ParseHeaders."):
        return PARSE_HEADERS_FIELD_EFFECTS.get(step_name.split(".", 1)[1], {})
    return STEP_CONTRACTS.get(step_name, {}).get("field_effects", {})


def _param_values(param_name: str, effect: dict, params: dict) -> list[str]:
    """The effective, upper-cased value(s) for a field-name param."""
    raw = params.get(param_name)
    if not raw and effect.get("default") is not None:
        raw = effect["default"]
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(v).strip().upper() for v in raw if str(v).strip()]
    return [str(raw).strip().upper()]


def fields_after_step(
    step_name: str,
    params: dict,
    before: set[str],
    before_confident: bool,
) -> tuple[set[str], bool]:
    """
    Update the tracked field-name set after a step, mirroring
    capabilities_after_step. ParseHeaders is bespoke (rename/delete/merge
    aren't expressible as plain "add a field"); everything else is driven by
    STEP_CONTRACTS' declarative produces_fields / field_effects.
    """
    if step_name.startswith("ParseHeaders."):
        return apply_parse_headers_field_changes(step_name, params, before, before_confident)

    if step_name not in STEP_CONTRACTS:
        return set(before), before_confident

    contract = STEP_CONTRACTS[step_name]
    result = set(before)
    confident = before_confident

    for name in contract.get("produces_fields", []):
        result.add(name)
        confident = True

    if step_name == "ConvertHeaders.imgt":
        # `simple` toggles the produced field set (see Annotation.py's
        # convertIMGTHeader) -- a bespoke case, like MaskPrimers' conditional
        # barcode_field below, rather than a static produces_fields entry.
        if params.get("simple"):
            confident = True
        else:
            result |= {"SPECIES", "REGION", "FUNCTIONALITY", "PARTIAL", "ACCESSION"}
            confident = True

    if step_name == "BuildConsensus.default":
        # build_consensus_group (app/presto_wrappers/build_consesus.py) merges
        # a *fixed* field name into the consensus record depending on whether
        # primer_freq is set -- PRIMER+PRCOUNT when it's absent, PRCONS+PRFREQ
        # when it's given -- rather than the param's own value becoming a
        # field name, so this can't be expressed as a plain field_effects
        # "field_name_new" entry the way e.g. MaskPrimers' barcode_field is.
        if params.get("primer_field"):
            if params.get("primer_freq") not in (None, ""):
                result |= {"PRCONS", "PRFREQ"}
            else:
                result |= {"PRIMER", "PRCOUNT"}
            confident = True

        # copy_fields/copy_actions summarize each existing field into the
        # consensus record independently of primer_field; "set"/"majority"
        # actions additionally derive a {field}_COUNT / {field}_FREQ field
        # alongside the field itself.
        copy_fields = params.get("copy_fields")
        copy_actions = params.get("copy_actions")
        if copy_fields and copy_actions:
            fields_list = copy_fields if isinstance(copy_fields, (list, tuple)) else [copy_fields]
            actions_list = copy_actions if isinstance(copy_actions, (list, tuple)) else [copy_actions]
            for field, action in zip(fields_list, actions_list):
                field_name = str(field).strip().upper()
                if not field_name:
                    continue
                action_lower = str(action).strip().lower()
                if action_lower == "set":
                    result.add(f"{field_name}_COUNT")
                    confident = True
                elif action_lower == "majority":
                    result.add(f"{field_name}_FREQ")
                    confident = True

    for param_name, effect in contract.get("field_effects", {}).items():
        if effect.get("type") != "field_name_new":
            continue
        when = effect.get("when")
        if when and not params.get(when):
            continue
        values = _param_values(param_name, effect, params)
        if values:
            result |= set(values)
            confident = True

    return result, confident


def fields_satisfy_contract(
    step_name: str,
    params: dict,
    lane_fields: dict[str, tuple[set[str], bool]],
    default_lane: str,
) -> str | None:
    """
    Checks every "field_name_existing" param against the tracked registry.

    lane_fields maps lane name -> (fields, confident) for every active lane,
    so a step whose params span two lanes (PairSeq's fields_1/fields_2,
    AssembleSeq's head_fields/tail_fields) can be checked against the right
    side. The check is skipped whenever that lane's registry isn't
    confident: an unconfirmed registry (e.g. a vendor header not yet run
    through ConvertHeaders) must never reject a value we simply don't know
    is wrong.
    """
    for param_name, effect in _field_effects_for(step_name).items():
        if effect.get("type") != "field_name_existing":
            continue

        lane = _resolve_lane(effect.get("lane"), params, default_lane)
        known, confident = lane_fields.get(lane, (set(), False))
        if not confident:
            continue

        values = _param_values(param_name, effect, params)
        if not values:
            continue

        for value in values:
            # ParseHeaders.table always emits ID as its first column
            # (parse_headers.py's SEQUENCE_ID_FIELD) no matter what the
            # tracked registry has seen -- pRESTO's parseAnnotation
            # synthesizes ID from the record's own identifier, never from a
            # domain annotation, which is exactly why
            # file_inspector.inspect_headers deliberately never adds it to
            # the registry (see its _ID_KEY comment). That correctly keeps
            # "ID" out of every other field-name check, but it also means
            # this one value could never pass here -- so it is exempted
            # instead of being permanently unselectable for this one param.
            if step_name == "ParseHeaders.table" and value == "ID":
                continue
            if value not in known:
                available = ", ".join(sorted(known)) or "none"
                return (
                    f"field '{value}' not found for parameter '{param_name}' "
                    f"on {lane} (available: {available})"
                )

    return None
