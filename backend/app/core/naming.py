"""
Human-readable names for everything a job writes to disk.

Before this, every run produced ``final.fastq`` plus ``R1_output.fastq`` in a
numbered step directory — indistinguishable once downloaded. Files are now
named after the dataset they came from and the code the user quotes to find
the run again, so a downloads folder holding a dozen runs still makes sense:

    <dataset>_<code>.fastq                          final output
    <dataset>_<code>_step03_MaskPrimers-score_R1.fastq   intermediate

``code`` is the tracking code when the run has one (that is the string the
user was emailed and the one they will search for); otherwise the first
segment of the job uuid, which is what the UI shows for untracked runs.
"""

from __future__ import annotations

import re
from pathlib import Path

# Everything outside this set becomes "_" so the name stays safe on every
# filesystem and inside a zip entry.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Extensions stripped from an uploaded file name before it becomes the dataset
# label — "sample_R1.fastq.gz" should read as "sample_R1", not "sample_R1.fastq".
_STRIPPED_SUFFIXES = (".gz", ".fastq", ".fq", ".fasta", ".fa", ".fas", ".tsv", ".csv")

MAX_DATASET_LEN = 48

# --- Path length -----------------------------------------------------------
# Windows refuses to open a path longer than 260 characters unless long-path
# support is switched on, which is not something a hosted app can assume. That
# ceiling is easy to hit here without anything looking unusual: the job
# workspace alone spends 74 characters on two uuids
# (jobs/<session>/<job>/steps/<step dir>/), and descriptive file names are the
# whole point of this module.
#
# So names are built to a budget instead of being built and hoped for. The
# caller works out how much room the directory leaves and the dataset label --
# the one part that is a convenience rather than an identifier -- gives way
# first. The run code is never dropped: without it a downloaded file cannot be
# traced back to its run, which is the reason any of this exists.
MAX_PATH_LEN = 260

# pRESTO appends its own label before the extension -- "_sample1-n10000",
# "_sorted-part000001", "_atleast-2" -- after we have chosen the name, so the
# budget has to leave room for one. A SplitSeq.group on a field with very long
# annotation values can still exceed this; that case fails with a clear message
# rather than silently truncating someone's data.
PRESTO_SUFFIX_RESERVE = 32

# Below this a dataset label is initials, not a name; drop it instead.
MIN_DATASET_LEN = 6

# Smallest stem that still identifies a file ("<code>_stepNN_<lane>"). If the
# workspace path does not leave even this, no naming scheme will help and the
# run is stopped up front with an explanation.
MIN_STEM_BUDGET = 24


def sanitize_token(value: str, fallback: str = "data") -> str:
    """Reduce arbitrary text to a safe, compact filename token."""
    cleaned = _UNSAFE.sub("_", str(value or "")).strip("._-")
    return cleaned or fallback


def dataset_label(original_name: str | None) -> str:
    """Dataset name for an uploaded file, e.g. "S1_R1.fastq.gz" → "S1_R1"."""
    name = Path(str(original_name or "")).name
    lowered = name.lower()
    for suffix in _STRIPPED_SUFFIXES:
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            lowered = name.lower()
    return sanitize_token(name, "dataset")[:MAX_DATASET_LEN]


def dataset_label_for_inputs(names: list[str] | None) -> str:
    """
    One dataset label for a whole run.

    Paired runs upload two files whose names usually differ only in the
    R1/R2 marker; using just the first would label every R2-derived file
    "…_R1", so the shared prefix is used when there is a useful one.
    """
    labels = [dataset_label(n) for n in (names or []) if n]
    if not labels:
        return "dataset"
    if len(labels) == 1:
        return labels[0]

    prefix = labels[0]
    for other in labels[1:]:
        while prefix and not other.startswith(prefix):
            prefix = prefix[:-1]
    # The overlap normally stops just after the read marker's separator
    # ("HD13M_R1"/"HD13M_R2" → "HD13M_R"); drop that dangling tail so the
    # label reads as the sample name. Only a separator-led tail is removed,
    # so a name that merely ends in "r" keeps its last letter.
    prefix = re.sub(r"[._-]+[Rr]?$", "", prefix.strip("._-"))
    # A one- or two-character overlap is coincidence, not a shared name.
    return prefix if len(prefix) >= 3 else labels[0]


def job_code(job_id: str, tracking_code: str | None = None) -> str:
    """The short identifier that ties a file back to one run."""
    if tracking_code:
        return sanitize_token(tracking_code, "job")
    return sanitize_token(str(job_id).split("-")[0], "job")


def run_prefix(dataset: str, job_id: str, tracking_code: str | None = None) -> str:
    """``<dataset>_<code>`` — the stem shared by every file of one run."""
    return f"{sanitize_token(dataset, 'dataset')}_{job_code(job_id, tracking_code)}"


def step_token(step_name: str) -> str:
    """"MaskPrimers.score" → "MaskPrimers-score" (a dot would read as an extension)."""
    return sanitize_token(str(step_name).replace(".", "-"), "step")


def step_stem(
    prefix: str,
    index: int,
    step_name: str,
    lane: str | None = None,
    budget: int | None = None,
) -> str:
    """
    Stem for one intermediate file: run prefix + step number + step + lane.

    ``budget`` is the number of characters available for the stem. When the
    full name does not fit, the dataset label is shortened and then dropped
    (see the MAX_PATH note above); the run code, step number, step name and
    lane are kept, because those are what make the file interpretable.
    """
    step = f"step{index:02d}"
    token = step_token(step_name)
    lane_part = sanitize_token(lane, "lane") if lane else ""
    dataset, _, code = prefix.rpartition("_")
    if not code:
        dataset, code = "", prefix

    def build(ds: str, with_step_name: bool) -> str:
        parts = [p for p in (ds, code, step) if p]
        if with_step_name:
            parts.append(token)
        if lane_part:
            parts.append(lane_part)
        return "_".join(parts)

    full = build(dataset, True)
    if budget is None or len(full) <= budget:
        return full

    # Give up the dataset label before anything else: it is a convenience,
    # while the code is what ties the file to a run and the step number and
    # name are what say where in the pipeline it came from.
    room = budget - len(build("", True)) - 1
    if room >= MIN_DATASET_LEN:
        return build(dataset[:room].rstrip("._-"), True)

    without_dataset = build("", True)
    if len(without_dataset) <= budget:
        return without_dataset

    # Still over: the step name is the last thing to go, since the file's
    # directory records it too.
    return build("", False)


def step_dir_name(index: int) -> str:
    """
    Directory holding one step's files: just the step number, e.g. "03".

    Every file inside already spells out the run, the step number, the step
    name and the lane, so naming the directory after the step too would spend
    twenty characters saying something the file already says -- and those
    characters come straight out of the file name's budget (see MAX_PATH
    above). Since a downloaded file keeps its name but not its directory, the
    file wins.
    """
    return f"{index:02d}"


def stem_budget(directory: str | Path, extension: str = ".fastq") -> int:
    """
    How many characters a file name may use inside ``directory``.

    Accounts for the separator, the extension and the label pRESTO appends
    afterwards. Returns 0 when the directory alone has already used the
    budget, which the caller should treat as unusable.
    """
    used = len(str(Path(directory).resolve())) + 1  # + path separator
    room = MAX_PATH_LEN - used - len(extension) - PRESTO_SUFFIX_RESERVE
    return max(0, room)
