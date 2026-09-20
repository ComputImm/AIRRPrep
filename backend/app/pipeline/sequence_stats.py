"""Sequence pass/fail counts for pipeline step reporting."""

from __future__ import annotations

from pathlib import Path

from presto.IO import countSeqFile, readSeqFile
from Bio import SeqIO
import logging

logger = logging.getLogger(__name__)


def count_sequences(file_path: str | None) -> int:
    """
    Count sequences in a file with fallback for duplicate keys.

    An empty file counts zero. pRESTO treats "file is empty" as a fatal error
    (countSeqFile calls printError, which raises SystemExit), but empty is a
    perfectly ordinary outcome here: a SplitSeq.group threshold that every read
    clears writes an empty "under" part, and a filter that rejects nothing
    writes an empty fail file. Letting that propagate killed runs whose real
    output -- the part the pipeline carries forward -- was fine.
    """
    if not file_path:
        return 0

    path = Path(file_path)
    if not path.is_file():
        return 0

    try:
        if path.stat().st_size == 0:
            return 0
    except OSError:
        return 0

    # Tables (ParseHeaders.table, AlignSets.table, EstimateError) carry one
    # header line, so the row count is lines - 1.
    if file_path.endswith((".tsv", ".csv", ".tab")):
        with open(path, "r", encoding="utf-8", errors="replace") as table_out:
            return max(0, sum(1 for _ in table_out) - 1)
    
    # Try counting sequences with proper error handling
    try:
        return int(countSeqFile(str(path)))
    except (ValueError, SystemExit) as e:
        error_msg = str(e)

        # A file with nothing in it but whitespace or a stray newline slips
        # past the size check above and reaches pRESTO, which calls it fatal.
        # It is not: zero sequences is zero sequences.
        if "is empty" in error_msg:
            logger.info("Empty sequence file %s, counting 0", file_path)
            return 0

        # If duplicate key error, try without indexing
        if "Duplicate key" in error_msg or "invalid" in error_msg:
            logger.warning(f"Duplicate key detected in {file_path}, using fallback count...")
            try:
                # Try with index=False
                seq_records = readSeqFile(str(path), index=False)
                return len(seq_records)
            except Exception as fallback_error:
                logger.warning(f"Fallback count failed: {fallback_error}, using Bio.SeqIO...")
                # Last resort: count with Biopython
                try:
                    # Detect file type from extension
                    file_type = "fasta"
                    if path.suffix.lower() in ['.fastq', '.fq']:
                        file_type = "fastq"
                    elif path.suffix.lower() in ['.fasta', '.fa', '.fna']:
                        file_type = "fasta"
                    
                    count = 0
                    for _ in SeqIO.parse(str(path), file_type):
                        count += 1
                    return count
                except Exception as bio_error:
                    logger.error(f"All counting methods failed for {file_path}: {bio_error}")
                    # Return 0 as last resort
                    return 0
        else:
            # Re-raise if it's not a duplicate key error
            logger.error(f"Error counting sequences in {file_path}: {e}")
            raise RuntimeError(f"Failed to count sequences in {file_path}: {e}") from e


def make_lane_stats(
    before: int,
    remaining: int,
    failed: int | None = None,
) -> dict[str, int]:
    if failed is None:
        failed = max(0, before - remaining)
    return {
        "before": before,
        "failed": failed,
        "remaining": remaining,
    }


def count_sequences_across(paths) -> int:
    """Total records over several files -- a step that fanned its lane out."""
    return sum(count_sequences(str(p)) for p in paths or [])


def stats_from_wrapper_result(before: int, result: object) -> dict[str, int] | None:
    if not isinstance(result, dict):
        return None

    # A table step turned reads into rows; nothing "failed", so report the rows
    # it wrote rather than letting before-minus-remaining invent a fail count.
    if "table_rows" in result:
        rows = int(result["table_rows"])
        return make_lane_stats(
            before=int(result.get("input_count", before) or before),
            remaining=rows,
            failed=max(0, int(result.get("input_count", before) or before) - rows),
        )

    if "pass_count" in result and "fail_count" in result:
        return make_lane_stats(
            before=before,
            remaining=int(result["pass_count"]),
            failed=int(result["fail_count"]),
        )

    if "unique_count" in result:
        remaining = int(result["unique_count"])
        duplicate = int(result.get("duplicate_count", 0))
        undetermined = int(result.get("undetermined_count", 0))
        return make_lane_stats(
            before=before,
            remaining=remaining,
            failed=duplicate + undetermined,
        )

    return None


def stats_from_output_file(before: int, output_path: str) -> dict[str, int]:
    remaining = count_sequences(output_path)
    return make_lane_stats(before=before, remaining=remaining)


def resolve_output_path(result: object, fallback: str) -> str:
    if isinstance(result, dict):
        if "pass" in result:
            return str(result["pass"])
        if "primary" in result:
            return str(result["primary"])
        if "unique_file" in result:
            return str(result["unique_file"])
    if isinstance(result, str):
        return result
    return fallback


def aggregate_lane_stats(by_lane: dict[str, dict[str, int]]) -> dict[str, int]:
    return {
        "before": sum(item["before"] for item in by_lane.values()),
        "failed": sum(item["failed"] for item in by_lane.values()),
        "remaining": sum(item["remaining"] for item in by_lane.values()),
    }


def build_step_stats_entry(
    index: int,
    step_name: str,
    by_lane: dict[str, dict[str, int]],
    output_paths: dict[str, str],
    parts: list[dict] | None = None,
) -> dict:
    """
    One row of the job's step_stats.

    `output_paths` holds the single file each lane carries forward. `parts` is
    the extra list a fan-out step produces -- every file it wrote, each with a
    label ("part3", "atleast-2", "SAMPLE-A") and its own record count, so the
    UI can offer them all for download instead of just the first.
    """
    totals = aggregate_lane_stats(by_lane)
    entry = {
        "index": index,
        "name": step_name,
        "lanes": list(by_lane.keys()),
        "before": totals["before"],
        "failed": totals["failed"],
        "remaining": totals["remaining"],
        "by_lane": by_lane,
        "output_paths": output_paths,
    }
    if parts:
        entry["parts"] = parts
    return entry