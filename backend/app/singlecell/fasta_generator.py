# app/singlecell/fasta_generator.py
"""
Writes the final standardized FASTA + metadata TSV from validated
UnifiedRecords.

Plain-text writer (not BioPython SeqRecord) so the FASTA header is provably
just ">{sequence_id}" with nothing else appended -- the simplest way to
guarantee zero annotation leakage into the header itself.
"""

import csv
from pathlib import Path

from app.singlecell.models import UnifiedRecord

_LINE_WIDTH = 70


def write_outputs(
    records: list[UnifiedRecord], outputs_dir: Path
) -> tuple[Path, Path]:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    fasta_path = outputs_dir / "final.fasta"
    tsv_path = outputs_dir / "metadata.tsv"

    with fasta_path.open("w") as fh:
        for record in records:
            fh.write(f">{record.sequence_id}\n")
            seq = record.sequence
            for i in range(0, len(seq), _LINE_WIDTH):
                fh.write(seq[i : i + _LINE_WIDTH] + "\n")

    fieldnames = list(UnifiedRecord.model_fields.keys())
    with tsv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump())

    return fasta_path, tsv_path


def write_source_annotations(
    records: list[UnifiedRecord],
    source_annotations: dict[str, dict[str, str]],
    field_order: list[str],
    outputs_dir: Path,
) -> Path | None:
    """Write source_annotations.tsv: every field the input carried, verbatim.

    The normalized output deliberately omits the upstream V(D)J calls,
    junctions and CDR3s so that sequences are re-annotated with one reference
    and procedure. Omitting them from the analysis schema is not a reason to
    destroy them, so they are written out beside it, one row per output
    record, keyed on the same ``sequence_id`` -- an inner join on that column
    reunites the two files exactly, with no collision and no loss.

    Returns None when the input carried nothing beyond what the normalized
    record already holds (no annotation source to preserve).
    """
    rows = [
        (record.sequence_id, source_annotations.get(record.sequence_id))
        for record in records
    ]
    if not any(values for _, values in rows):
        return None

    outputs_dir.mkdir(parents=True, exist_ok=True)
    path = outputs_dir / "source_annotations.tsv"
    # Every column the source declared, in the source's own order, including
    # one that happens to be empty in every row: dropping such a column would
    # lose the fact that the input carried it, and "lossless" has to mean the
    # column set as well as the values.
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["sequence_id", *field_order])
        for sequence_id, values in rows:
            values = values or {}
            writer.writerow(
                [sequence_id, *(values.get(f, "") for f in field_order)]
            )
    return path
