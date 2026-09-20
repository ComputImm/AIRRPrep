import inspect

from app.pipeline.contracts import STEP_CONTRACTS
from app.pipeline.parse_headers_effects import PARSE_HEADERS_FIELD_EFFECTS
from app.pipeline.registry import PIPELINE_FUNCTIONS
from app.pipeline.stream import get_step_stream_behavior


def _field_effects_for(step_name: str, contract: dict) -> dict:
    """
    Single source of truth for "is this param a field name": the same table
    step_parameter_analyzer.py uses to mutate/validate planner.LaneState.fields
    (see contracts.py's module docstring). Surfacing it here as `field_kind`
    is what lets the frontend render a dropdown of real field names instead
    of hand-maintaining a second, parallel list of field-name params in
    TypeScript.
    """
    if step_name.startswith("ParseHeaders."):
        return PARSE_HEADERS_FIELD_EFFECTS.get(step_name.split(".", 1)[1], {})
    return contract.get("field_effects", {})


def normalize_type(annotation):

    if isinstance(annotation, type):
        return annotation.__name__

    if annotation == inspect.Parameter.empty:
        return "string"

    if annotation == int:
        return "integer"

    if annotation == float:
        return "float"

    if annotation == bool:
        return "boolean"

    if annotation == str:
        return "string"

    if annotation == list:
        return "array"

    return str(annotation)


# Parameter names the executor (app/pipeline/executor.py) binds itself from
# the run's actual files/format/output directory before calling a wrapper --
# never something a user should type. Every wrapper in this codebase uses one
# of these exact names for its file-path/out_args/file_type plumbing (see the
# `run_*_step` functions), so filtering on the name is safe and complete.
# Without this, every step's UI form gained bogus *required* "seq_file" /
# "out_file" (and, for paired/merged steps, "seq_file_1"/"seq_file_2"/
# "head_file"/"tail_file"/"output_file"/"out_args") text fields that users had
# to fill with junk before a step could be added at all -- whatever they typed
# was silently overwritten by the executor anyway.
HIDDEN_PARAMS = frozenset({
    "data",
    "seq_file", "out_file",
    "seq_file_1", "seq_file_2",
    "head_file", "tail_file", "output_file",
    "out_args", "file_type",
})


def extract_parameters(func, field_effects: dict | None = None):

    signature = inspect.signature(func)

    parameters = []
    field_effects = field_effects or {}

    for name, param in signature.parameters.items():

        if name in HIDDEN_PARAMS:
            continue

        required = param.default == inspect.Parameter.empty

        default = None if required else param.default
        annotation = normalize_type(param.annotation)
        if annotation == "string" and default is not None:
            annotation = type(default).__name__

        effect = field_effects.get(name)
        field_kind = None
        if effect and effect.get("type") in ("field_name_new", "field_name_existing"):
            field_kind = "list" if effect.get("multi") else "single"

        parameter_info = {
            "name": name,
            "required": required,
            "default": default,
            "type": annotation,
            "kind": str(param.kind),
            # None for every ordinary param; "single" or "list" for a param
            # that names an existing (or new) header field -- the frontend
            # renders these as a dropdown of the pipeline's actual known
            # fields at this stage instead of a free-text box.
            "field_kind": field_kind,
        }

        parameters.append(parameter_info)

    return parameters


def _step_description(func) -> str:
    doc = inspect.getdoc(func) or ""
    if not doc:
        return ""
    return doc.strip().split("\n\n")[0].replace("\n", " ")


def get_step_metadata(step_name):

    if step_name not in PIPELINE_FUNCTIONS:
        raise Exception(f"Unknown step: {step_name}")

    func = PIPELINE_FUNCTIONS[step_name]
    contract = STEP_CONTRACTS.get(step_name, {})

    # Prefer the curated pRESTO description from the contract; fall back to the
    # wrapper/tool docstring when none is provided.
    description = contract.get("description") or _step_description(func)

    return {
        "step": step_name,
        "function": func.__name__,
        "module": func.__module__,
        "description": description,
        "stream_behavior": get_step_stream_behavior(step_name).value,
        "requires_files": contract.get("requires_files", []),
        "requires_executable": contract.get("requires_executable", []),
        "output_type": contract.get("output_type", "same"),
        # "always" / "conditional" / None -- whether this step fans its lane
        # out into several files, which ends the pipeline. See
        # app/pipeline/splitting.py; the UI warns before such a step is added.
        "splits_output": contract.get("splits_output"),
        "parameters": extract_parameters(func, _field_effects_for(step_name, contract)),
    }


def get_all_steps_metadata():

    results = []

    for step_name in PIPELINE_FUNCTIONS:

        try:
            metadata = get_step_metadata(step_name)
            results.append(metadata)

        except Exception as e:
            results.append({
                "step": step_name,
                "error": str(e),
            })

    return results
