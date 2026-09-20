"""
Which steps fan one lane out into several files, and what that means.

pRESTO's SplitSeq subcommands do not all behave alike. ``select`` filters and
writes one file; ``count`` and ``group`` shard the lane into an arbitrary
number of parts (20 000 reads at max_count=4 000 is five files, and a
``group`` on a free-text annotation is one file per distinct value). The rest
sit in between: ``group`` shards per distinct value unless a numeric
``threshold`` turns it into the bounded two-way ``under``/``atleast`` split the
ready-made pipelines rely on, ``sort`` shards only when max_count is given, and
``sample`` only when more than one sample size is requested.

A lane that has been fanned out is no longer a single stream, so the pipeline
**ends there**: the parts are the run's output and every one of them is
downloadable. Continuing would mean re-running the whole tail of the pipeline
once per part — unbounded work and disk for a request that never said how
many parts there would be — and every downstream structure here (the
PipelineStream's one-path-per-lane model, per-step pass/fail stats, the
retention funnel, the step-download endpoint) assumes one file per lane.

This module is the single place that answers "does this step, with these
parameters, split?" — the planner, the validator and the executor all ask it,
so the builder can never offer a step that the executor would then refuse.
"""

from __future__ import annotations

from typing import Any

#: Steps that always fan out, whatever their parameters.
ALWAYS_SPLITTING = frozenset({"SplitSeq.count"})

#: Steps that fan out only for certain parameter values.
CONDITIONAL_SPLITTING = frozenset(
    {"SplitSeq.group", "SplitSeq.sort", "SplitSeq.sample", "SplitSeq.samplepair"}
)

SPLITTING_STEPS = ALWAYS_SPLITTING | CONDITIONAL_SPLITTING


def _count_of(value: Any) -> int:
    """How many outputs a max_count parameter asks for."""
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set)):
        return len([v for v in value if v is not None and v != ""])
    return 1


def step_splits_output(step_name: str, params: dict | None = None) -> bool:
    """True when this step writes more than one file per input lane."""
    if step_name in ALWAYS_SPLITTING:
        return True
    if step_name not in CONDITIONAL_SPLITTING:
        return False

    params = params or {}
    if step_name == "SplitSeq.group":
        # A numeric threshold is the bounded two-way "under"/"atleast" split
        # (the DUPCOUNT>=2 idiom the ready-made pipelines use, which carries
        # "atleast" forward). Without one it is a file per distinct value.
        return params.get("threshold") in (None, "")
    if step_name == "SplitSeq.sort":
        # sortSeqFile only starts a new part when max_count is supplied.
        return params.get("max_count") not in (None, "")
    # sample / samplepair write one file (or one pair) per requested size.
    return _count_of(params.get("max_count")) > 1


def split_reason(step_name: str, params: dict | None = None) -> str | None:
    """Human explanation of why a step ends the pipeline, or None."""
    if not step_splits_output(step_name, params):
        return None
    params = params or {}
    if step_name == "SplitSeq.count":
        max_count = params.get("max_count")
        detail = f" of at most {max_count} reads each" if max_count else ""
        return f"SplitSeq.count writes one file per partition{detail}"
    if step_name == "SplitSeq.group":
        field = params.get("field")
        detail = f" of {str(field).upper()}" if field else ""
        return (
            f"SplitSeq.group without a threshold writes one file per distinct "
            f"value{detail}"
        )
    if step_name == "SplitSeq.sort":
        return (
            f"SplitSeq.sort with max_count={params.get('max_count')} writes one "
            "file per partition"
        )
    return (
        f"{step_name} writes one output per requested sample size "
        f"({_count_of(params.get('max_count'))} requested)"
    )


def terminal_message(step_name: str, params: dict | None = None) -> str:
    """The message shown when a user tries to build past a splitting step."""
    reason = split_reason(step_name, params) or f"{step_name} splits the output"
    return (
        f"{reason}, so it has to be the last step: the pipeline cannot "
        "continue past a split. Download the parts and start a new run from "
        "the one you want."
    )
