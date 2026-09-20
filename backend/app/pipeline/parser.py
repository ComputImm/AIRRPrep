from app.pipeline.presto_params import sanitize_presto_params

_ASSEMBLE_MODES = frozenset({"align", "join", "reference", "sequential"})
_PARSE_HEADERS_MODES = frozenset({
    "add", "collapse", "copy", "delete", "expand", "merge", "rename", "table",
})
_SPLIT_SEQ_MODES = frozenset({
    "count", "group", "sample", "samplepair", "sort", "select",
})


def _resolve_step_name(step: dict) -> str:
    step_name = step["name"]
    raw_params = dict(step.get("params") or {})

    if step_name in ("ParseHeaders", "ParseHeaders.default"):
        mode = str(raw_params.pop("command", "table")).lower()
        if mode not in _PARSE_HEADERS_MODES:
            raise ValueError(
                f"ParseHeaders command must be one of: "
                f"{', '.join(sorted(_PARSE_HEADERS_MODES))}"
            )
        step["_resolved_params"] = raw_params
        return f"ParseHeaders.{mode}"

    if step_name in ("AssembleSeq", "AssembleSeq.default"):
        mode = str(raw_params.pop("command", "align")).lower()
        if mode not in _ASSEMBLE_MODES:
            raise ValueError(
                f"AssembleSeq command must be one of: "
                f"{', '.join(sorted(_ASSEMBLE_MODES))}"
            )
        step["_resolved_params"] = raw_params
        return f"AssembleSeq.{mode}"

    if step_name in ("SplitSeq", "SplitSeq.default"):
        mode = str(raw_params.pop("command", "select")).lower()
        if mode not in _SPLIT_SEQ_MODES:
            raise ValueError(
                f"SplitSeq command must be one of: "
                f"{', '.join(sorted(_SPLIT_SEQ_MODES))}"
            )
        step["_resolved_params"] = raw_params
        return f"SplitSeq.{mode}"

    if "." not in step_name:
        return f"{step_name}.default"

    return step_name


def parse_steps(selected_steps):

    parsed = []

    for step in selected_steps:
        step_name = _resolve_step_name(step)
        params = step.pop("_resolved_params", None)
        if params is None:
            params = step.get("params", {})

        entry = {
            "id": step["id"],
            "name": step_name,
            "params": sanitize_presto_params(params),
        }

        if "lanes" in step:
            entry["lanes"] = step["lanes"]
        elif "lane" in step:
            entry["lanes"] = step["lane"]

        parsed.append(entry)

    return parsed


def parse_steps_params(selected_steps_params: dict):
    parsed = []

    for step_name, step_params in selected_steps_params.items():
        if "." in step_name:
            selected_steps_params[f"{step_name}.default"] = step_params

    return parsed
