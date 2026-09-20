"""
Wrappers for pRESTO UnifyHeaders (one function per subcommand).

Synchronous replacement for UnifyHeaders.unifyHeaders: the same
consensusUnify / deletionUnify collapse applied per annotation group, driven
in-process instead of through manageProcesses.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from Bio import SeqIO

from presto.Defaults import default_barcode_field
from presto.IO import getFileType, printLog, readSeqFile
from presto.Multiprocessing import SeqData
from presto.Sequence import consensusUnify, deletionUnify, indexSeqSets

from app.pipeline.presto_params import normalize_delimiter
from app.presto_tools.UnifyHeaders import default_unify_field


def _run_unify_headers(
    seq_file: str,
    out_file: str,
    collapse_func,
    command: str,
    set_field: str = default_barcode_field,
    unify_field: str = default_unify_field,
    delimiter=None,
) -> dict[str, Any]:
    """Collapse `unify_field` within each `set_field` group."""
    delim = normalize_delimiter(delimiter)
    set_field = str(set_field).upper()
    unify_field = str(unify_field).upper()

    log = OrderedDict()
    log["START"] = "UnifyHeaders"
    log["COMMAND"] = command
    log["FILE"] = Path(seq_file).name
    log["SET_FIELD"] = set_field
    log["UNIFY_FIELD"] = unify_field
    printLog(log)

    in_type = getFileType(seq_file)
    seq_records = SeqIO.to_dict(readSeqFile(seq_file))
    grouped = indexSeqSets(seq_records, field=set_field, delimiter=delim)

    out_path = Path(out_file)
    fail_path = out_path.with_name(f"{out_path.stem}_fail{out_path.suffix}")

    pass_count = fail_count = 0
    with open(out_path, "w") as pass_handle, open(fail_path, "w") as fail_handle:
        for group_id, seq_keys in grouped.items():
            seq_list = [seq_records[key] for key in seq_keys]
            result = collapse_func(
                SeqData(group_id, seq_list), field=unify_field, delimiter=delim
            )

            if result.valid:
                records = list(result.results)
                SeqIO.write(records, pass_handle, in_type)
                pass_count += len(records)
            else:
                fail_count += len(seq_list)
                SeqIO.write(seq_list, fail_handle, in_type)

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
    final_log["END"] = "UnifyHeaders"
    printLog(final_log)

    return {
        "pass": str(out_path),
        "fail": str(fail_path) if fail_count else None,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_unify_headers_consensus(
    seq_file: str,
    out_file: str,
    set_field: str = default_barcode_field,
    unify_field: str = default_unify_field,
    delimiter=None,
) -> dict[str, Any]:
    """
    Reassigns an annotation field to its per-group consensus value
    (UnifyHeaders.py consensus). Every read in the group keeps its place.
    """
    return _run_unify_headers(
        seq_file,
        out_file,
        consensusUnify,
        command="consensus",
        set_field=set_field,
        unify_field=unify_field,
        delimiter=delimiter,
    )


def run_unify_headers_delete(
    seq_file: str,
    out_file: str,
    set_field: str = default_barcode_field,
    unify_field: str = default_unify_field,
    delimiter=None,
) -> dict[str, Any]:
    """
    Deletes whole groups whose reads disagree on the annotation field
    (UnifyHeaders.py delete).
    """
    return _run_unify_headers(
        seq_file,
        out_file,
        deletionUnify,
        command="delete",
        set_field=set_field,
        unify_field=unify_field,
        delimiter=delimiter,
    )
