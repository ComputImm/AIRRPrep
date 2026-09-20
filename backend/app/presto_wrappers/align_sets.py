"""
Wrappers for pRESTO AlignSets (one function per subcommand).

`muscle` and `offset` are synchronous replacements for AlignSets.alignSets —
same per-group alignment as AlignSets.processQueue, but driven in-process
instead of through manageProcesses (see build_consesus.py for the same
pattern). `table` calls AlignSets.writeOffsetFile directly.
"""

from __future__ import annotations

import shutil
from collections import OrderedDict, deque
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path
from typing import Any

from Bio import SeqIO

from presto.Applications import runMuscle
from presto.Defaults import default_barcode_field, default_primer_field
from presto.IO import getFileType, printLog, readSeqFile
from presto.Sequence import calculateDiversity, indexSeqSets

from app.config import EXTERNAL_TOOL_CPUS, MUSCLE_BIN
from app.pipeline.presto_params import merge_out_args, normalize_delimiter
from app.presto_tools.AlignSets import offsetSeqSet, readOffsetFile
from app.presto_wrappers.helper import resolve_uploaded_file


def require_executable(name: str, tool: str) -> str:
    """
    Resolve an external aligner/clustering binary or fail with a clear error.

    The name always comes from configuration (app.config), never from step
    parameters — see the note on MUSCLE_BIN / CLUSTER_BINS in app/config.py.
    """
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(
            f"{tool} needs the '{name}' executable, which was not found on "
            f"PATH. Install it on the worker host or choose another step."
        )
    return resolved


def _restore_quality(seq_list, align_list) -> None:
    """Re-insert phred scores into a gapped alignment (0 for gap columns)."""
    first = seq_list[0]
    has_quality = hasattr(first, "letter_annotations") and (
        "phred_quality" in first.letter_annotations
    )
    if not has_quality:
        return

    qual_dict = {
        seq.id: seq.letter_annotations["phred_quality"] for seq in seq_list
    }
    for seq in align_list:
        qual = deque(qual_dict[seq.id])
        seq.letter_annotations["phred_quality"] = [
            0 if c == "-" else qual.popleft() for c in seq.seq
        ]


def _align_group(task):
    """Align one barcode group. Module level so a pool worker can import it."""
    align_func, seq_list, align_args = task
    try:
        return list(align_func(seq_list, **align_args))
    except Exception:
        return None


def _aligned_groups(align_func, align_args, seq_lists, workers, batch_size=500):
    """
    Align barcode groups across `workers` processes, yielding in input order.

    MUSCLE takes no thread option and pRESTO runs it once per barcode group, so
    the only way to spend more than one core on this step is to have several of
    those alignments in flight at once. Batched for the same reason as the
    assembly pool: map() would otherwise pull every group into memory first.
    """
    if workers <= 1:
        for seq_list in seq_lists:
            yield _align_group((align_func, seq_list, align_args))
        return

    with ProcessPoolExecutor(max_workers=workers) as pool:
        while True:
            batch = list(islice(seq_lists, batch_size))
            if not batch:
                break
            yield from pool.map(
                _align_group,
                [(align_func, seq_list, align_args) for seq_list in batch],
                chunksize=max(1, len(batch) // (workers * 4)),
            )


def _run_align_sets(
    seq_file: str,
    out_file: str,
    align_func,
    align_args: dict,
    command: str,
    barcode_field: str = default_barcode_field,
    calc_div: bool = False,
    delimiter=None,
    workers: int = 1,
) -> dict[str, Any]:
    """Multiple-align each barcode group; groups that fail alignment fail out."""
    delim = normalize_delimiter(delimiter)
    barcode_field = str(barcode_field).upper()

    log = OrderedDict()
    log["START"] = "AlignSets"
    log["COMMAND"] = command
    log["FILE"] = Path(seq_file).name
    log["BARCODE_FIELD"] = barcode_field
    log["CALC_DIV"] = calc_div
    printLog(log)

    in_type = getFileType(seq_file)
    seq_records = SeqIO.to_dict(readSeqFile(seq_file))
    grouped = indexSeqSets(seq_records, field=barcode_field, delimiter=delim)

    out_path = Path(out_file)
    fail_path = out_path.with_name(f"{out_path.stem}_fail{out_path.suffix}")

    pass_count = fail_count = 0
    aligned = _aligned_groups(
        align_func,
        align_args,
        ([seq_records[key] for key in keys] for keys in grouped.values()),
        workers,
    )
    with open(out_path, "w") as pass_handle, open(fail_path, "w") as fail_handle:
        for (group_id, seq_keys), align_list in zip(grouped.items(), aligned):
            seq_list = [seq_records[key] for key in seq_keys]

            if align_list is None:
                fail_count += len(seq_list)
                SeqIO.write(seq_list, fail_handle, in_type)
                continue

            align_list = list(align_list)
            if calc_div:
                group_log = OrderedDict()
                group_log["BARCODE"] = group_id
                group_log["SEQCOUNT"] = len(seq_list)
                group_log["DIVERSITY"] = calculateDiversity(align_list)
                printLog(group_log)

            _restore_quality(seq_list, align_list)
            SeqIO.write(align_list, pass_handle, in_type)
            pass_count += len(align_list)

    if fail_count == 0:
        try:
            fail_path.unlink()
        except OSError:
            pass

    final_log = OrderedDict()
    final_log["OUTPUT"] = out_path.name
    final_log["SETS"] = len(grouped)
    final_log["PASS"] = pass_count
    final_log["FAIL"] = fail_count
    final_log["END"] = "AlignSets"
    printLog(final_log)

    return {
        "pass": str(out_path),
        "fail": str(fail_path) if fail_count else None,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_align_sets_muscle(
    seq_file: str,
    out_file: str,
    barcode_field: str = default_barcode_field,
    calc_div: bool = False,
    delimiter=None,
) -> dict[str, Any]:
    """
    Multiple aligns each barcode set with MUSCLE (AlignSets.py muscle).
    Requires the muscle executable on the worker host (config.MUSCLE_BIN).
    """
    exec_path = require_executable(MUSCLE_BIN, "AlignSets.muscle")
    return _run_align_sets(
        seq_file,
        out_file,
        runMuscle,
        {"aligner_exec": exec_path},
        command="muscle",
        barcode_field=barcode_field,
        calc_div=calc_div,
        delimiter=delimiter,
        # The offset subcommand stays serial: it is pure Python and spawns
        # nothing, so a pool would only add process overhead.
        workers=EXTERNAL_TOOL_CPUS,
    )


def run_align_sets_offset(
    seq_file: str,
    out_file: str,
    offset_file: str,
    barcode_field: str = default_barcode_field,
    primer_field: str = default_primer_field,
    offset_mode: str = "pad",
    calc_div: bool = False,
    delimiter=None,
) -> dict[str, Any]:
    """
    Aligns each barcode set using a table of primer offsets (AlignSets.py offset).
    offset_file is an uploaded file_id for the tab-delimited offset table
    produced by the table subcommand.
    """
    mode = str(offset_mode).lower()
    if mode not in ("pad", "cut"):
        raise ValueError("offset_mode must be 'pad' or 'cut'")

    offset_dict = readOffsetFile(resolve_uploaded_file(offset_file))

    return _run_align_sets(
        seq_file,
        out_file,
        offsetSeqSet,
        {
            "offset_dict": offset_dict,
            "field": str(primer_field).upper(),
            "mode": mode,
            "delimiter": normalize_delimiter(delimiter),
        },
        command="offset",
        barcode_field=barcode_field,
        calc_div=calc_div,
        delimiter=delimiter,
    )


def run_align_sets_table(
    out_file: str,
    primer_file: str,
    reverse: bool = False,
    delimiter=None,
) -> dict[str, Any]:
    """
    Builds a 5' (or 3') offset table by multiple aligning a primer FASTA
    (AlignSets.py table). Output is a TSV, not sequences — it ends the
    sequence stream and is meant to be re-uploaded for the offset subcommand.
    Requires the muscle executable on the worker host (config.MUSCLE_BIN).
    """
    from app.presto_tools.AlignSets import writeOffsetFile

    exec_path = require_executable(MUSCLE_BIN, "AlignSets.table")
    out_path = Path(out_file)
    out_args = merge_out_args(out_path.parent, {"out_name": out_path.stem})
    out_args["out_type"] = "tab"
    out_args["delimiter"] = normalize_delimiter(delimiter)

    written = writeOffsetFile(
        resolve_uploaded_file(primer_file),
        align_func=runMuscle,
        align_args={"aligner_exec": exec_path},
        reverse=bool(reverse),
        out_file=str(out_path),
        out_args=out_args,
    )

    # Unlike ParseHeaders.table, real pRESTO's writeOffsetFile writes no
    # header row (one line per primer) -- generic .tsv row counting
    # (app/pipeline/sequence_stats.count_sequences) assumes every table has
    # one, which undercounted by exactly one row and, with a single primer,
    # reported the table as empty and aborted the run. Returning the row
    # count directly sidesteps that guess entirely, the same way
    # ParseHeaders.table does.
    with open(written, "r", encoding="utf-8", errors="replace") as handle:
        row_count = sum(1 for _ in handle)

    return {
        "primary": written,
        "outputs": [written],
        "table_rows": row_count,
        "input_count": row_count,
    }
