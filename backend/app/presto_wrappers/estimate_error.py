"""
Wrappers for pRESTO EstimateError (one function per subcommand).

`barcode` is already single-process in EstimateError, so it is called directly.
`set` is a synchronous replacement for EstimateError.estimateSets — the same
per-set mismatch counting (processEEQueue) and aggregation (collectEEQueue),
driven in-process instead of through manageProcesses.

Both subcommands emit tab-delimited error tables rather than sequences, so they
end the sequence stream (output_type "tab" in contracts.py). The first table is
copied to the step's output path; the rest are listed in ``extra_outputs``.
"""

from __future__ import annotations

import shutil
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from Bio import SeqIO

from presto.Defaults import (
    default_barcode_field,
    default_consensus_min_freq,
    default_consensus_min_qual,
)
from presto.IO import countSeqFile, getFileType, printLog, readSeqFile
from presto.Sequence import (
    calculateDiversity,
    frequencyConsensus,
    indexSeqSets,
    qualityConsensus,
)

from app.pipeline.presto_params import merge_out_args, normalize_delimiter
from app.presto_tools.EstimateError import (
    countMismatches,
    default_distance_types,
    default_headers,
    default_min_count,
    default_nucleotides,
    estimateBarcode,
    initializeMismatchDictionary,
    writeResults,
)


def _out_args(out_file: str, delimiter) -> dict:
    out_path = Path(out_file)
    out_args = merge_out_args(out_path.parent, {"out_name": out_path.stem})
    out_args["out_type"] = "tab"
    out_args["delimiter"] = normalize_delimiter(delimiter)
    return out_args


def _primary_output(out_file: str, produced: tuple | list) -> str:
    """Copy the first produced table onto the step's output path."""
    files = [str(f) for f in produced if f]
    if not files:
        raise RuntimeError("EstimateError produced no output files")

    out_path = Path(out_file)
    primary = Path(files[0])
    if primary.resolve() != out_path.resolve():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(primary, out_path)
    return str(out_path)


def _table_row_count(path: str) -> int:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def _add_counter_dict(dict1: dict, dict2: dict) -> dict:
    join = Counter(dict1)
    join.update(Counter(dict2))
    return dict(join)


def _update_total_mismatch(total_mismatch: dict, mismatch: dict) -> dict:
    """collectEEQueue._updateTotalMismatch, verbatim."""
    for head in default_headers:
        total_mismatch["qual"][head] = _add_counter_dict(
            total_mismatch["qual"][head], mismatch["qual"][head]
        )
        total_mismatch["set"][head] = _add_counter_dict(
            total_mismatch["set"][head], mismatch["set"][head]
        )
        total_mismatch["pos"][head] = _add_counter_dict(
            total_mismatch["pos"][head], mismatch["pos"][head]
        )
        for nucleotide in mismatch["nuc"]["mismatch"]:
            total_mismatch["nuc"][head][nucleotide] = _add_counter_dict(
                total_mismatch["nuc"][head][nucleotide],
                mismatch["nuc"][head][nucleotide],
            )
    for head in default_distance_types:
        total_mismatch["dist"][head] = (
            total_mismatch["dist"][head] + mismatch["dist"][head]
        )

    return total_mismatch


def _set_mismatch(seq_list, cons_func, cons_args, min_count, max_diversity):
    """processEEQueue for a single set: mismatch counts, or None when it fails."""
    if len(seq_list) < min_count:
        return None

    init_len = len(seq_list[0])
    if any(len(seq) != init_len for seq in seq_list):
        return None

    if max_diversity is not None:
        if calculateDiversity(seq_list) > max_diversity:
            return None

    ref_seq = cons_func(seq_list, **cons_args)
    return countMismatches(seq_list, ref_seq)


def run_estimate_error_set(
    seq_file: str,
    out_file: str,
    set_field: str = default_barcode_field,
    min_count: int = default_min_count,
    mode: str = "freq",
    min_qual: float = default_consensus_min_qual,
    min_freq: float = default_consensus_min_freq,
    max_diversity: float | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """
    Estimates error statistics within annotation sets (EstimateError.py set).
    Requires FASTQ input. Writes six tables: error by position, quality,
    nucleotide and set size, plus the pairwise distance and threshold tables.
    """
    if getFileType(seq_file) != "fastq":
        raise ValueError("EstimateError.set requires FASTQ input (quality scores)")

    mode = str(mode).lower()
    if mode == "freq":
        cons_func, cons_args = frequencyConsensus, {"min_freq": min_freq}
    elif mode == "qual":
        cons_func = qualityConsensus
        cons_args = {
            "min_qual": min_qual,
            "min_freq": min_freq,
            "dependent": False,
        }
    else:
        raise ValueError("mode must be 'freq' or 'qual'")

    delim = normalize_delimiter(delimiter)
    set_field = str(set_field).upper()

    log = OrderedDict()
    log["START"] = "EstimateError"
    log["COMMAND"] = "set"
    log["FILE"] = Path(seq_file).name
    log["MODE"] = mode
    log["SET_FIELD"] = set_field
    log["MIN_COUNT"] = min_count
    log["MAX_DIVERSITY"] = max_diversity
    printLog(log)

    seq_records = SeqIO.to_dict(readSeqFile(seq_file))
    grouped = indexSeqSets(seq_records, field=set_field, delimiter=delim)

    total_mismatch = initializeMismatchDictionary(
        0,
        nucleotides=default_nucleotides,
        headers=default_headers,
        distance_types=default_distance_types,
    )

    set_count = seq_count = pass_count = fail_count = 0
    for seq_keys in grouped.values():
        seq_list = [seq_records[key] for key in seq_keys]
        set_count += 1
        seq_count += len(seq_list)

        mismatch = _set_mismatch(
            seq_list, cons_func, cons_args, min_count, max_diversity
        )
        if mismatch is None:
            fail_count += 1
            continue

        pass_count += 1
        total_mismatch = _update_total_mismatch(total_mismatch, mismatch)

    if pass_count == 0:
        raise RuntimeError(
            "EstimateError.set found no usable annotation sets — every set was "
            f"below min_count={min_count}, had unequal read lengths, or exceeded "
            "max_diversity."
        )

    # --- collectEEQueue assembly -------------------------------------------
    nuc_dict = {
        head: {
            (n1, n2): total_mismatch["nuc"][head][n1][n2]
            for n2 in default_nucleotides
            for n1 in default_nucleotides
            if n1 != n2
        }
        for head in default_headers
    }

    pos_df = pd.DataFrame.from_dict(total_mismatch["pos"])
    qual_df = pd.DataFrame.from_dict(total_mismatch["qual"])
    nuc_df = pd.DataFrame.from_dict(nuc_dict)
    set_df = pd.DataFrame.from_dict(total_mismatch["set"])
    dist_df = pd.DataFrame.from_dict(total_mismatch["dist"])
    dist_df.index = dist_df.index / len(dist_df.index)

    # Threshold: average minimum between the mode and 0.75 of the tail.
    dist = total_mismatch["dist"]["all"]
    dist = dist[np.argmax(dist):]
    window = dist[: int(len(dist) * 0.75)]
    thresh_df = pd.DataFrame.from_dict(
        {
            "thresh": {
                "ALL": dist_df.index[
                    np.argmax(dist)
                    + int(
                        np.mean(
                            [
                                index
                                for index in np.argsort(window)
                                if dist[index] == np.min(window)
                            ]
                        )
                    )
                ]
            }
        }
    )

    for frame in (pos_df, nuc_df, qual_df, set_df):
        frame["error"] = frame["mismatch"] / frame["total"]
        # Bound the minimum error to Q=90.
        frame.loc[frame["error"] == 0, "error"] = 1e-9
        frame["emp_q"] = -10 * np.log10(frame["error"])
        frame["rep_q"] = frame["q_sum"] / frame["total"]

    assembled = {
        "pos": pos_df,
        "qual": qual_df,
        "nuc": nuc_df,
        "set": set_df,
        "dist": dist_df,
        "thresh": thresh_df,
    }
    out_files = writeResults(assembled, seq_file, _out_args(out_file, delimiter))

    final_log = OrderedDict()
    for i, name in enumerate(out_files, start=1):
        final_log["OUTPUT%i" % i] = Path(name).name
    final_log["SETS"] = set_count
    final_log["SEQUENCES"] = seq_count
    final_log["PASS"] = pass_count
    final_log["FAIL"] = fail_count
    final_log["POSITION_ERROR"] = "%.6f" % (
        pos_df["mismatch"].sum() / pos_df["total"].sum()
    )
    final_log["NUCLEOTIDE_ERROR"] = "%.6f" % (
        nuc_df["mismatch"].sum() / nuc_df["total"].sum() * 3
    )
    final_log["QUALITY_ERROR"] = "%.6f" % (
        qual_df["mismatch"].sum() / qual_df["total"].sum()
    )
    final_log["SET_ERROR"] = "%.6f" % (
        set_df["mismatch"].sum() / set_df["total"].sum()
    )
    final_log["ALL_THRESHOLD"] = "%.6f" % thresh_df["thresh"]["ALL"]
    final_log["END"] = "EstimateError"
    printLog(final_log)

    # A distance/threshold table has no natural pRESTO "pass/fail read" count
    # of its own; generic .tsv row counting (sequence_stats.count_sequences)
    # assumed one header line and compared it against `before` (the *previous*
    # step's sequence count, unrelated to this table), producing a
    # nearly-all-failed-looking stat on every run. table_rows/input_count are
    # this step's own honest counts instead, the same pattern ParseHeaders.table
    # uses.
    primary = _primary_output(out_file, out_files)
    return {
        "primary": primary,
        "extra_outputs": [str(f) for f in out_files],
        "table_rows": _table_row_count(primary),
        "input_count": seq_count,
    }


def run_estimate_error_barcode(
    seq_file: str,
    out_file: str,
    barcode_field: str = default_barcode_field,
    pad_ends: str = "none",
    delimiter=None,
) -> dict[str, Any]:
    """
    Calculates pairwise distance metrics of barcode sequences
    (EstimateError.py barcode). Writes the distance and threshold tables used
    to pick a barcode clustering cut-off.
    """
    pad_ends = str(pad_ends).lower()
    if pad_ends not in ("none", "head", "tail"):
        raise ValueError("pad_ends must be 'none', 'head' or 'tail'")

    out_files = estimateBarcode(
        seq_file,
        barcode_field=str(barcode_field).upper(),
        distance_types=default_distance_types,
        pad_ends=pad_ends,
        out_args=_out_args(out_file, delimiter),
    )

    primary = _primary_output(out_file, out_files)
    return {
        "primary": primary,
        "extra_outputs": [str(f) for f in out_files],
        "table_rows": _table_row_count(primary),
        "input_count": countSeqFile(seq_file),
    }
