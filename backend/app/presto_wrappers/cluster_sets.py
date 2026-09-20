"""
Wrappers for pRESTO ClusterSets (one function per subcommand).

`all` and `barcode` are already single-process in ClusterSets, so they are
called directly. `set` is a synchronous replacement for ClusterSets.clusterSets
— the same per-group clustering as ClusterSets.processQueue, driven in-process
instead of through manageProcesses.

Every subcommand shells out to an external clustering tool (usearch, vsearch or
cd-hit-est), which must be installed on the worker host.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from Bio import SeqIO

from presto.Annotation import flattenAnnotation, mergeAnnotation, parseAnnotation
from presto.Applications import default_max_memory
from presto.Defaults import default_barcode_field, default_cluster_field
from presto.IO import getFileType, printLog, readSeqFile
from presto.Sequence import indexSeqSets

from app.config import CLUSTER_BINS, DEFAULT_CLUSTER_TOOL, EXTERNAL_TOOL_CPUS
from app.pipeline.presto_params import merge_out_args, normalize_delimiter
from app.presto_tools.ClusterSets import (
    choices_cluster_tool,
    clusterAll,
    clusterBarcodes,
    default_cluster_ident,
    default_cluster_prefix,
    default_length_ratio,
    map_cluster_tool,
    min_cluster_ident,
)
from app.presto_wrappers.align_sets import require_executable


def _resolve_cluster_tool(cluster_tool: str, ident: float):
    """
    Validate the tool/identity pair and resolve the configured executable.

    The binary comes from app.config.CLUSTER_BINS, never from step parameters
    (pRESTO's --exec has no safe equivalent in a hosted service).

    An unset tool resolves to DEFAULT_CLUSTER_TOOL (vsearch), not to pRESTO's
    own default of USEARCH: USEARCH is proprietary and is not redistributed
    with AIRRPrep or its image, so defaulting to it would silently produce a
    step that cannot run on a stock deployment.
    """
    tool = str(cluster_tool or DEFAULT_CLUSTER_TOOL).lower()
    if tool not in choices_cluster_tool:
        raise ValueError(
            f"cluster_tool must be one of {', '.join(choices_cluster_tool)}"
        )
    if float(ident) < min_cluster_ident[tool]:
        raise ValueError(
            f"identity {ident} is too low for clustering tool {tool} "
            f"(minimum {min_cluster_ident[tool]})"
        )
    try:
        exec_path = require_executable(CLUSTER_BINS[tool], f"ClusterSets ({tool})")
    except RuntimeError as e:
        if tool == "usearch":
            raise RuntimeError(
                "ClusterSets with USEARCH needs a USEARCH binary, which is "
                "proprietary and is not distributed with AIRRPrep or its "
                "container image. Install your own licensed copy on the "
                "worker and point USEARCH_BIN at it, or choose vsearch or "
                "cd-hit-est, which the image provides."
            ) from e
        raise
    return tool, map_cluster_tool[tool], exec_path


def _cluster_out_args(out_file: str, delimiter) -> dict:
    out_path = Path(out_file)
    out_args = merge_out_args(out_path.parent, {"out_name": out_path.stem})
    out_args["delimiter"] = normalize_delimiter(delimiter)
    return out_args


def run_cluster_sets_set(
    seq_file: str,
    out_file: str,
    set_field: str = default_barcode_field,
    ident: float = default_cluster_ident,
    length_ratio: float = default_length_ratio,
    seq_start: int = 0,
    seq_end: int | None = None,
    cluster_field: str = default_cluster_field,
    cluster_prefix: str = default_cluster_prefix,
    cluster_tool: str = DEFAULT_CLUSTER_TOOL,
    cluster_memory: int = default_max_memory,
    delimiter=None,
) -> dict[str, Any]:
    """
    Clusters reads by sequence data within barcode groups (ClusterSets.py set).
    Adds a CLUSTER annotation naming the within-group cluster.
    """
    tool, cluster_func, exec_path = _resolve_cluster_tool(cluster_tool, ident)
    delim = normalize_delimiter(delimiter)
    set_field = str(set_field).upper()
    cluster_field = str(cluster_field).upper()

    log = OrderedDict()
    log["START"] = "ClusterSets"
    log["COMMAND"] = "set"
    log["FILE"] = Path(seq_file).name
    log["IDENTITY"] = ident
    log["SET_FIELD"] = set_field
    log["CLUSTER_FIELD"] = cluster_field
    log["CLUSTER_TOOL"] = tool
    printLog(log)

    cluster_args = {
        "cluster_exec": exec_path,
        "ident": ident,
        "length_ratio": length_ratio,
        "seq_start": seq_start,
        "seq_end": seq_end,
        "max_memory": cluster_memory,
        # usearch/vsearch/cd-hit-est take the thread count directly, so this
        # step needs no pool of its own -- the tool does its own threading.
        "threads": EXTERNAL_TOOL_CPUS,
    }

    in_type = getFileType(seq_file)
    seq_records = SeqIO.to_dict(readSeqFile(seq_file))
    grouped = indexSeqSets(seq_records, field=set_field, delimiter=delim)

    out_path = Path(out_file)
    fail_path = out_path.with_name(f"{out_path.stem}_fail{out_path.suffix}")

    pass_count = fail_count = cluster_total = 0
    with open(out_path, "w") as pass_handle, open(fail_path, "w") as fail_handle:
        for seq_keys in grouped.values():
            seq_list = [seq_records[key] for key in seq_keys]
            cluster_dict = cluster_func(seq_list, **cluster_args)

            if cluster_dict is None:
                fail_count += len(seq_list)
                SeqIO.write(seq_list, fail_handle, in_type)
                continue

            cluster_total += len(cluster_dict)
            seq_dict = {s.id: s for s in seq_list}
            results = []
            for cluster, id_list in cluster_dict.items():
                label = f"{cluster_prefix}{cluster}"
                for seq_id in id_list:
                    seq = seq_dict[seq_id]
                    header = parseAnnotation(seq.description, delimiter=delim)
                    header = mergeAnnotation(
                        header, {cluster_field: label}, delimiter=delim
                    )
                    seq.id = seq.name = flattenAnnotation(header, delimiter=delim)
                    seq.description = ""
                    results.append(seq)

            # A partial clustering loses reads, so the whole set fails (this is
            # the `result.valid` check in ClusterSets.processQueue).
            if len(results) != len(seq_dict):
                fail_count += len(seq_list)
                SeqIO.write(seq_list, fail_handle, in_type)
                continue

            SeqIO.write(results, pass_handle, in_type)
            pass_count += len(results)

    if fail_count == 0:
        try:
            fail_path.unlink()
        except OSError:
            pass

    final_log = OrderedDict()
    final_log["OUTPUT"] = out_path.name
    final_log["SETS"] = len(grouped)
    final_log["CLUSTERS"] = cluster_total
    final_log["PASS"] = pass_count
    final_log["FAIL"] = fail_count
    final_log["END"] = "ClusterSets"
    printLog(final_log)

    return {
        "pass": str(out_path),
        "fail": str(fail_path) if fail_count else None,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_cluster_sets_all(
    seq_file: str,
    out_file: str,
    ident: float = default_cluster_ident,
    length_ratio: float = default_length_ratio,
    seq_start: int = 0,
    seq_end: int | None = None,
    cluster_field: str = default_cluster_field,
    cluster_prefix: str = default_cluster_prefix,
    cluster_tool: str = DEFAULT_CLUSTER_TOOL,
    cluster_memory: int = default_max_memory,
    delimiter=None,
) -> str:
    """
    Clusters all sequences regardless of annotation (ClusterSets.py all).
    Adds a CLUSTER annotation naming the cluster each read landed in.
    """
    tool, _, exec_path = _resolve_cluster_tool(cluster_tool, ident)

    return clusterAll(
        seq_file,
        ident=ident,
        length_ratio=length_ratio,
        seq_start=seq_start,
        seq_end=seq_end,
        cluster_field=str(cluster_field).upper(),
        cluster_prefix=cluster_prefix,
        cluster_memory=cluster_memory,
        cluster_tool=tool,
        cluster_exec=exec_path,
        # Reaches the clustering tool as its --threads argument. Left unset it
        # arrives as None, which runUSEARCH/runVSearch drop rather than pass on
        # -- correct, but it leaves the tool on its own single-threaded default.
        nproc=EXTERNAL_TOOL_CPUS,
        out_file=str(out_file),
        out_args=_cluster_out_args(out_file, delimiter),
    )


def run_cluster_sets_barcode(
    seq_file: str,
    out_file: str,
    barcode_field: str = default_barcode_field,
    ident: float = default_cluster_ident,
    length_ratio: float = default_length_ratio,
    cluster_field: str = default_cluster_field,
    cluster_prefix: str = default_cluster_prefix,
    cluster_tool: str = DEFAULT_CLUSTER_TOOL,
    cluster_memory: int = default_max_memory,
    delimiter=None,
) -> str:
    """
    Clusters reads by clustering their barcode sequences (ClusterSets.py barcode).
    Adds a CLUSTER annotation grouping reads whose UMI/barcode cluster together.
    """
    tool, _, exec_path = _resolve_cluster_tool(cluster_tool, ident)

    return clusterBarcodes(
        seq_file,
        ident=ident,
        length_ratio=length_ratio,
        barcode_field=str(barcode_field).upper(),
        cluster_field=str(cluster_field).upper(),
        cluster_prefix=cluster_prefix,
        cluster_memory=cluster_memory,
        cluster_tool=tool,
        cluster_exec=exec_path,
        # As above: without this the tool runs on its own default width.
        nproc=EXTERNAL_TOOL_CPUS,
        out_file=str(out_file),
        out_args=_cluster_out_args(out_file, delimiter),
    )
