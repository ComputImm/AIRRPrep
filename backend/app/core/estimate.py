"""
Rough "how long will this take?" model, used to decide whether a run must be
gated behind a verified email address.

This is a *sizing heuristic*, not a scheduler. Its one job is to separate the
runs a user can sit and watch from the ones where they should be told to go
away and wait for an email. So it errs on the side of over-estimating: being
offered a notification for a run that turns out to be quick is a mild
annoyance, while a user staring at a progress bar for four hours is not.

Two things drive the estimate:

* **Input size.** Everything downstream is a streaming pass over the reads,
  so megabytes in is the dominant term.
* **Which components are in the pipeline.** Throughput varies by more than an
  order of magnitude between steps — ``FilterSeq`` is a per-read predicate,
  while ``MaskPrimers align`` runs a local alignment against every primer for
  every read, and TRUST4 does a full de-novo assembly. The per-step rates in
  ``STEP_THROUGHPUT_MB_S`` encode that.

The rates are deliberately declared in one table so a deployment that finds
them badly wrong on its own hardware can retune them in one place.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.config import (
    NOTIFY_MIN_INPUT_MB,
    NOTIFY_MIN_SECONDS,
    TRUST4_THREADS,
)

_MB = 1024 * 1024

# Input megabytes each step chews through per second, at roughly the scale
# this service runs at. Keyed by the resolved "Family.mode" step name that
# app/pipeline/parser.py produces.
STEP_THROUGHPUT_MB_S: dict[str, float] = {
    # Per-read predicates — essentially IO bound.
    "FilterSeq.length": 14.0,
    "FilterSeq.quality": 12.0,
    "FilterSeq.missing": 14.0,
    "FilterSeq.repeats": 10.0,
    "FilterSeq.trimqual": 12.0,
    "FilterSeq.maskqual": 12.0,
    # Header rewrites and splits — cheap.
    "ParseHeaders.add": 20.0,
    "ParseHeaders.collapse": 18.0,
    "ParseHeaders.copy": 20.0,
    "ParseHeaders.delete": 20.0,
    "ParseHeaders.expand": 18.0,
    "ParseHeaders.merge": 18.0,
    "ParseHeaders.rename": 20.0,
    "ParseHeaders.table": 20.0,
    "SplitSeq.count": 12.0,
    "SplitSeq.group": 10.0,
    "SplitSeq.sample": 12.0,
    "SplitSeq.samplepair": 10.0,
    "SplitSeq.sort": 8.0,
    "SplitSeq.select": 12.0,
    # Pairing walks both mates and joins on the read id.
    "PairSeq.default": 8.0,
    # Primer handling: `score` is a fixed-offset comparison, `align` runs a
    # local alignment per primer per read and is an order of magnitude slower.
    "MaskPrimers.score": 4.0,
    "MaskPrimers.extract": 10.0,
    "MaskPrimers.align": 0.4,
    # The genuinely expensive ones.
    "BuildConsensus.default": 1.5,
    "CollapseSeq.default": 1.0,
    "AssembleSeq.align": 1.5,
    "AssembleSeq.join": 8.0,
    "AssembleSeq.reference": 0.5,
    "AssembleSeq.sequential": 0.5,
}

# Used when a step name is not in the table (a newly added component). Slow
# enough that an unknown step biases towards offering the notification.
DEFAULT_THROUGHPUT_MB_S = 2.0

# Steps worth naming to the user as the reason a run is slow, mapped to the
# label shown in the UI.
HEAVY_STEP_LABELS: dict[str, str] = {
    "BuildConsensus.default": "BuildConsensus",
    "CollapseSeq.default": "CollapseSeq",
    "AssembleSeq.align": "AssemblePairs (align)",
    "AssembleSeq.reference": "AssemblePairs (reference)",
    "AssembleSeq.sequential": "AssemblePairs (sequential)",
    "MaskPrimers.align": "MaskPrimers (align)",
}

# Fixed cost per step: process start-up, reading and re-writing the
# intermediate files in the job workspace.
PER_STEP_OVERHEAD_S = 5.0

# TRUST4 de-novo assembly, per thread. Assembly dominates every other stage of
# a raw-read single-cell run by so much that the rest is not worth modelling.
TRUST4_THROUGHPUT_MB_S_PER_THREAD = 0.06
# Parsing an already-assembled single-cell input (Cell Ranger contigs, a
# TRUST4 barcode report, a plain FASTA) is a single tabular pass.
SINGLECELL_PARSE_MB_S = 15.0


@dataclass
class JobEstimate:
    """What the UI needs to explain the gate to the user."""

    #: Total bytes of input across every uploaded file for this run.
    total_input_bytes: int = 0
    #: Best-guess wall-clock runtime, in seconds.
    estimated_seconds: float = 0.0
    #: Whether a verified email address is required before this may start.
    requires_email: bool = False
    #: Human-readable labels of the slow components in this pipeline.
    heavy_steps: list[str] = field(default_factory=list)
    #: Short phrases explaining *why* the gate applied, for the dialog copy.
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_input_bytes": self.total_input_bytes,
            "total_input_mb": round(self.total_input_bytes / _MB, 1),
            "estimated_seconds": round(self.estimated_seconds),
            "requires_email": self.requires_email,
            "heavy_steps": self.heavy_steps,
            "reasons": self.reasons,
        }


def _total_bytes(file_paths) -> int:
    total = 0
    for path in file_paths:
        try:
            total += Path(path).stat().st_size
        except OSError:
            # A missing file is the job-start path's problem to report, not
            # the estimator's — treat it as contributing nothing.
            continue
    return total


def _decide(estimate: JobEstimate, input_mb: float) -> JobEstimate:
    """
    Apply the configured thresholds and fill in the user-facing reasons.

    Only runtime and input size gate a run. The presence of a slow component
    deliberately does not: its cost is already in ``estimated_seconds`` via
    the throughput table, and gating on it separately would demand an email
    for a 5 MB test run through a pipeline that merely *contains*
    BuildConsensus. Heavy steps are named as an explanation once some other
    threshold has tripped.
    """
    if estimate.estimated_seconds >= NOTIFY_MIN_SECONDS:
        estimate.requires_email = True
        estimate.reasons.append("this run is expected to take a while")

    if input_mb >= NOTIFY_MIN_INPUT_MB:
        estimate.requires_email = True
        estimate.reasons.append(f"the uploaded files total {input_mb:.0f} MB")

    if estimate.requires_email:
        if estimate.heavy_steps:
            estimate.reasons.append(
                "it includes slow components (" + ", ".join(estimate.heavy_steps) + ")"
            )
        if not estimate.reasons:
            # Reached by a caller that set requires_email itself (TRUST4).
            estimate.reasons.append("this kind of run takes a long time")

    return estimate


def estimate_bulk_job(file_paths, steps) -> JobEstimate:
    """
    Estimate a bulk pRESTO run.

    ``steps`` are the parsed steps (resolved "Family.mode" names) that
    app/pipeline/parser.py produces. Lane assignment is ignored: a step that
    only touches R1 does roughly half the work, but that refinement is well
    inside the noise of a heuristic this coarse.
    """
    total_bytes = _total_bytes(file_paths)
    input_mb = total_bytes / _MB

    seconds = 0.0
    heavy: list[str] = []
    for step in steps:
        name = step.get("name") if isinstance(step, dict) else getattr(step, "name", "")
        rate = STEP_THROUGHPUT_MB_S.get(name, DEFAULT_THROUGHPUT_MB_S)
        seconds += input_mb / rate + PER_STEP_OVERHEAD_S

        label = HEAVY_STEP_LABELS.get(name)
        if label and label not in heavy:
            heavy.append(label)

    return _decide(
        JobEstimate(
            total_input_bytes=total_bytes,
            estimated_seconds=seconds,
            heavy_steps=heavy,
        ),
        input_mb,
    )


def estimate_singlecell_job(file_paths, needs_assembly: bool) -> JobEstimate:
    """
    Estimate a single-cell run.

    ``needs_assembly`` is whether the chosen format routes through TRUST4
    (see TRUST4_ASSEMBLY_FORMATS). Those runs are gated unconditionally: a
    de-novo assembly of raw 10x reads runs for hours, and no one should be
    asked to keep a browser tab open for that.
    """
    total_bytes = _total_bytes(file_paths)
    input_mb = total_bytes / _MB

    if not needs_assembly:
        estimate = JobEstimate(
            total_input_bytes=total_bytes,
            estimated_seconds=input_mb / SINGLECELL_PARSE_MB_S + PER_STEP_OVERHEAD_S,
        )
        return _decide(estimate, input_mb)

    threads = max(int(TRUST4_THREADS or 1), 1)
    rate = TRUST4_THROUGHPUT_MB_S_PER_THREAD * threads
    return _decide(
        JobEstimate(
            total_input_bytes=total_bytes,
            estimated_seconds=input_mb / rate + 120.0,
            heavy_steps=["TRUST4 assembly"],
            requires_email=True,
        ),
        input_mb,
    )
