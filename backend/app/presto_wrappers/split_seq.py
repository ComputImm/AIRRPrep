"""
Wrappers for pRESTO SplitSeq (one function per subcommand).

Several of these write more than one file per input lane, and how many is not
knowable until the data has been read: `count` shards by size, `group` writes
one file per distinct annotation value. Rather than hide that behind a single
"primary" path, each wrapper reports **every** file it produced, in the
`outputs` list, so the executor can record them all as downloadable results.

`primary` is the file the pipeline would carry forward. It only matters for the
subcommands that do not really fan out (`select`, `sort` without max_count,
`group` with a numeric threshold, a single-size `sample`); after a genuine
fan-out the pipeline stops (app/pipeline/splitting.py) and `primary` is just
the first part.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.file_store import get_file
from app.pipeline.presto_params import merge_out_args, normalize_delimiter
from app.presto_tools.SplitSeq import (
    downsizeSeqFile,
    groupSeqFile,
    samplePairSeqFile,
    sampleSeqFile,
    selectSeqFile,
    sortSeqFile,
)


def _int_list(value: Any, param: str) -> list[int]:
    """
    Coerce a sample-size parameter into a list of ints.

    pRESTO formats these with "%i" ("Sampling n=%i" % n), so a string sinks the
    run with "%i format: a real number is required, not str". Everything from a
    browser form arrives as text, and a saved pipeline replays whatever was
    stored, so the wrapper does not assume the caller sanitized it.
    """
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in items:
        if item is None or item == "":
            continue
        try:
            out.append(int(str(item).strip()))
        except (TypeError, ValueError):
            raise ValueError(
                f"{param} must be a whole number of reads; got {item!r}"
            ) from None
    if not out:
        raise ValueError(f"{param} is required")
    return out


def _resolve_uploaded_file(file_id: str) -> str:
    stored = get_file(file_id)
    if stored is None:
        raise ValueError(f"File not found: {file_id}")
    return stored.path


def _out_args(step_dir: Path, out_file: str, file_type: str | None, delimiter) -> dict:
    out_path = Path(out_file)
    out_args = merge_out_args(step_dir, {"out_name": out_path.stem})
    if file_type:
        out_args["out_type"] = file_type
    out_args["delimiter"] = normalize_delimiter(delimiter)
    return out_args


def _label_of(path: str, out_file: str) -> str:
    """
    The part name pRESTO appended: "part000003", "atleast-2", "SAMPLE-A", ...

    Files come back as {out_name}_{label}.{ext} (see presto.IO.getOutputHandle),
    so stripping the shared stem leaves the label -- which is what the UI shows
    next to each download.
    """
    stem = Path(path).stem
    prefix = f"{Path(out_file).stem}_"
    label = stem[len(prefix):] if stem.startswith(prefix) else stem
    # "part000003" reads better as "part3".
    match = re.fullmatch(r"part0*(\d+)", label)
    if match:
        return f"part{int(match.group(1))}"
    return label or "output"


def _result(
    out_file: str,
    produced: list[str] | str,
    primary: str | None = None,
) -> dict[str, Any]:
    """Normalize a pRESTO return into {primary, outputs, parts}."""
    files = [produced] if isinstance(produced, str) else [str(f) for f in produced]
    if not files:
        raise RuntimeError("SplitSeq produced no output files")

    # Sorted so ordering is stable across runs, and so the threshold split puts
    # "atleast" (the part pRESTO workflows carry forward) ahead of "under".
    files = sorted(dict.fromkeys(files))
    chosen = str(primary) if primary else files[0]

    return {
        "primary": chosen,
        "outputs": files,
        "parts": [{"label": _label_of(f, out_file), "path": f} for f in files],
    }


def run_split_seq_count(
    seq_file: str,
    out_file: str,
    max_count: int,
    file_type: str | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """
    Splits a sequence file into parts holding at most max_count reads each
    (SplitSeq count). 20,000 reads at max_count=4,000 produces 5 files.
    """
    out_path = Path(out_file)
    out_args = _out_args(out_path.parent, out_file, file_type, delimiter)
    files = downsizeSeqFile(seq_file, max_count, out_args)
    return _result(out_file, files)


def run_split_seq_group(
    seq_file: str,
    out_file: str,
    field: str,
    threshold: float | None = None,
    file_type: str | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """
    Splits sequences by annotation field (SplitSeq group).

    With a threshold this is the bounded two-way under/at-least split, and the
    at-least part is the primary -- matching how pRESTO workflows use it (e.g.
    keeping DUPCOUNT >= 2). Without one it is one file per distinct value.
    """
    field = str(field).upper()
    out_path = Path(out_file)
    out_args = _out_args(out_path.parent, out_file, file_type, delimiter)
    files = groupSeqFile(seq_file, field, threshold=threshold, out_args=out_args)
    primary = None
    if threshold is not None:
        primary = next((f for f in files if "atleast" in Path(f).stem.lower()), None)
    return _result(out_file, files, primary=primary)


def run_split_seq_sample(
    seq_file: str,
    out_file: str,
    max_count: list[int],
    field: str | None = None,
    values: list[str] | None = None,
    file_type: str | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """
    Random sampling (SplitSeq sample): one output file per size in max_count.
    """
    if field:
        field = str(field).upper()
    max_count = _int_list(max_count, "max_count")
    out_path = Path(out_file)
    out_args = _out_args(out_path.parent, out_file, file_type, delimiter)
    files = sampleSeqFile(
        seq_file,
        max_count,
        field=field,
        values=values,
        out_args=out_args,
    )
    if not files:
        raise RuntimeError("SplitSeq sample produced no output files")
    # The last entry is the largest sample -- the most useful to carry forward.
    return _result(out_file, files, primary=str(files[-1]))


def run_split_seq_samplepair(
    seq_file_1: str,
    seq_file_2: str,
    max_count: list[int],
    field: str | None = None,
    values: list[str] | None = None,
    coord_type: str = "presto",
    out_args: dict | None = None,
) -> dict[str, Any]:
    """
    Paired-end sampling (SplitSeq samplepair): one R1/R2 pair per size in
    max_count. Reports the last (largest) pair as the primary, plus every pair.
    """
    if field:
        field = str(field).upper()
    max_count = _int_list(max_count, "max_count")
    merged = merge_out_args(overrides=out_args)
    pairs = samplePairSeqFile(
        seq_file_1,
        seq_file_2,
        max_count,
        field=field,
        values=values,
        coord_type=coord_type,
        out_args=merged,
    )
    if not pairs:
        raise RuntimeError("SplitSeq samplepair produced no output")

    last = pairs[-1]
    return {
        "primary": str(last[0]),
        "primary_r2": str(last[1]),
        "outputs": [str(f) for pair in pairs for f in pair],
        "parts": [
            {"label": f"sample{i + 1}-{lane}", "path": str(path)}
            for i, pair in enumerate(pairs)
            for lane, path in (("R1", pair[0]), ("R2", pair[1]))
        ],
    }


def run_split_seq_sort(
    seq_file: str,
    out_file: str,
    field: str,
    numeric: bool = False,
    max_count: int | None = None,
    file_type: str | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """
    Sort sequences by annotation field (SplitSeq sort). One file, unless
    max_count also partitions the sorted reads.
    """
    field = str(field).upper()
    out_path = Path(out_file)
    out_args = _out_args(out_path.parent, out_file, file_type, delimiter)
    files = sortSeqFile(
        seq_file,
        field,
        numeric=numeric,
        max_count=max_count,
        out_args=out_args,
    )
    return _result(out_file, files)


def run_split_seq_select(
    seq_file: str,
    out_file: str,
    field: str,
    value_list: list[str] | None = None,
    value_file: str | None = None,
    negate: bool = False,
    file_type: str | None = None,
    delimiter=None,
) -> str:
    """
    Select reads by annotation values (SplitSeq select). Writes a single file,
    so the pipeline can continue after it.
    value_file may be an uploaded file_id (TSV with a column matching field).
    """
    field = str(field).upper()
    out_path = Path(out_file)
    out_args = _out_args(out_path.parent, out_file, file_type, delimiter)
    resolved_value_file = None
    if value_file:
        resolved_value_file = _resolve_uploaded_file(value_file)

    return selectSeqFile(
        seq_file,
        field,
        value_list=value_list,
        value_file=resolved_value_file,
        negate=negate,
        out_file=str(out_path),
        out_args=out_args,
    )
