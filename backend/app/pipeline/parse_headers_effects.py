"""
Capability changes caused by ParseHeaders subcommands.

Maps annotation field names (params.fields / names / name) to Capability via
capabilities.ANNOTATION_FIELD_TO_CAPABILITY.
"""

from app.pipeline.capabilities import (
    Capability,
    capability_for_annotation_field,
)


def _as_upper_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().upper()] if value.strip() else []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _caps_for_fields(fields: list[str]) -> set[Capability]:
    caps: set[Capability] = set()
    for field in fields:
        cap = capability_for_annotation_field(field)
        if cap:
            caps.add(cap)
    return caps


def apply_parse_headers_capability_changes(
    step_name: str,
    params: dict,
    before: set[Capability],
) -> set[Capability]:
    """
    Update lane capabilities after a ParseHeaders step.

    step_name: ParseHeaders.add | collapse | copy | delete | expand | merge | rename | table
    """
    if not step_name.startswith("ParseHeaders."):
        return set(before)

    mode = step_name.split(".", 1)[1]
    result = set(before)

    if mode == "table":
        # table emits a TSV and ends the sequence stream; no capability change.
        return result

    # Any header-editing ParseHeaders step marks the stream as having parsed
    # headers (mirrors `produces: PARSED_HEADER` in contracts.py).
    result.add(Capability.PARSED_HEADER)

    fields = _as_upper_list(params.get("fields"))

    if mode == "add":
        result |= _caps_for_fields(fields)
        return result

    if mode == "delete":
        result -= _caps_for_fields(fields)
        return result

    if mode == "copy":
        names = _as_upper_list(params.get("names"))
        result |= _caps_for_fields(fields)
        result |= _caps_for_fields(names)
        return result

    if mode == "rename":
        names = _as_upper_list(params.get("names"))
        for old, new in zip(fields, names):
            old_cap = capability_for_annotation_field(old)
            new_cap = capability_for_annotation_field(new)
            if old_cap and old != new:
                result.discard(old_cap)
            if new_cap:
                result.add(new_cap)
        return result

    if mode == "merge":
        merge_name = params.get("name")
        merge_names = _as_upper_list(merge_name)
        merged_cap = _caps_for_fields(merge_names)
        field_caps = _caps_for_fields(fields)

        if params.get("delete"):
            result -= field_caps
        else:
            result |= field_caps

        result |= merged_cap
        return result

    if mode in ("collapse", "expand"):
        result |= _caps_for_fields(fields)
        return result

    return result


# ---------------------------------------------------------------------------
# Field-name registry effects (parallel to the capability changes above, but
# tracking concrete field-name strings rather than the coarser Capability
# enum -- see planner.LaneState.fields). Single source of truth for which
# ParseHeaders params are field-name params, consumed by both
# step_parameter_analyzer.py (mutation + job-launch validation) and
# metadata.py (the `field_kind` the frontend renders a dropdown for).
#
# "field_name_new": the param's value(s) become new field names.
# "field_name_existing": the param's value(s) must already exist in the lane
#   (validation-only; contracts.py uses the same two type names for every
#   other step, see STEP_CONTRACTS[...]['field_effects']).
# ---------------------------------------------------------------------------
PARSE_HEADERS_FIELD_EFFECTS: dict[str, dict[str, dict]] = {
    "add": {"fields": {"type": "field_name_new", "multi": True}},
    "collapse": {"fields": {"type": "field_name_existing", "multi": True}},
    "copy": {
        "fields": {"type": "field_name_existing", "multi": True},
        "names": {"type": "field_name_new", "multi": True},
    },
    "delete": {"fields": {"type": "field_name_existing", "multi": True}},
    "expand": {"fields": {"type": "field_name_existing", "multi": True}},
    "merge": {
        "fields": {"type": "field_name_existing", "multi": True},
        "name": {"type": "field_name_new", "multi": False},
    },
    "rename": {
        "fields": {"type": "field_name_existing", "multi": True},
        "names": {"type": "field_name_new", "multi": True},
    },
    "table": {
        "fields": {"type": "field_name_existing", "multi": True, "optional": True}
    },
}


def apply_parse_headers_field_changes(
    step_name: str,
    params: dict,
    before: set[str],
    before_confident: bool,
) -> tuple[set[str], bool]:
    """
    Update the tracked field-name registry after a ParseHeaders step.

    Mirrors apply_parse_headers_capability_changes' per-subcommand dispatch,
    but on the concrete field-name set rather than the Capability enum.
    """
    if not step_name.startswith("ParseHeaders."):
        return set(before), before_confident

    mode = step_name.split(".", 1)[1]
    result = set(before)
    fields = _as_upper_list(params.get("fields"))

    if mode == "add":
        result |= set(fields)
        return result, True

    if mode == "delete":
        result -= set(fields)
        return result, True

    if mode == "copy":
        names = _as_upper_list(params.get("names"))
        result |= set(fields) | set(names)
        return result, True

    if mode == "rename":
        names = _as_upper_list(params.get("names"))
        for old, new in zip(fields, names):
            if old != new:
                result.discard(old)
            result.add(new)
        return result, True

    if mode == "merge":
        merge_names = _as_upper_list(params.get("name"))
        if params.get("delete"):
            result -= set(fields)
        result |= set(merge_names)
        return result, True

    if mode == "expand":
        # pRESTO invents the split field names (FIELD1, FIELD2, ...) from the
        # data itself, not from params -- the registry can't name them, so
        # stop trusting it as exhaustive rather than silently omitting them.
        return result, False

    # collapse / table: values change, the field-name set itself doesn't.
    return result, before_confident
