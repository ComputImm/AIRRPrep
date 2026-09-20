# app/singlecell/adapters/cellranger_adapter.py
"""
Cell Ranger VDJ adapter — covers all three Cell Ranger output shapes the
product spec lists, since they only differ in which files are provided and
which columns carry which value (contig CSV vs AIRR TSV):

  - all_contig.fasta + all_contig_annotations.csv        (variant="all_contig")
  - filtered_contig.fasta + filtered_contig_annotations.csv (variant="filtered_contig")
  - Cell Ranger AIRR rearrangement TSV                    (variant="airr_tsv")

Cell Ranger's contig_annotations.csv carries the V(D)J call as
chain/v_gene/d_gene/j_gene/c_gene/cdr3/cdr3_nt columns -- these are Cell
Ranger's own names for exactly the annotation-leakage concept the product
spec bans by AIRR name (v_call, junction, ...). strip_leakage_fields() knows
about both naming conventions (see validator.py), so they're dropped here
before ever reaching a UnifiedRecord.
"""

import csv
import logging
from pathlib import Path

from app.singlecell.adapters._util import (
    first_present,
    parse_bool,
    parse_int,
    read_fasta_dict,
)
from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import UnifiedRecord
from app.singlecell.validator import strip_leakage_fields

logger = logging.getLogger("celery_worker")

_CONTIG_VARIANTS = {"all_contig", "filtered_contig"}


class CellRangerAdapter(SingleCellAdapter):
    format_id = "cellranger_vdj_all"  # overridden per-instance below

    def __init__(self, variant: str, allow_productive: bool = False):
        super().__init__()
        if variant not in _CONTIG_VARIANTS | {"airr_tsv"}:
            raise ValueError(f"Unknown Cell Ranger variant: {variant}")
        self.variant = variant
        # `productive` is the one borderline column in the spec: it is listed
        # in the pre-IMGT record, but only "if source == CR and user
        # explicitly allows it — otherwise null. Mark as annotation-derived
        # in logs." Cell Ranger is the only source that can supply it, and it
        # stays null unless the caller opts in, because deciding a sequence is
        # productive requires knowing the reading frame — an IMGT call.
        self.allow_productive = allow_productive
        self.format_id = {
            "all_contig": "cellranger_vdj_all",
            "filtered_contig": "cellranger_vdj_filtered",
            "airr_tsv": "cellranger_airr_tsv",
        }[variant]

    def _productive(self, raw_row: dict) -> bool | None:
        if not self.allow_productive:
            return None
        return parse_bool(first_present(raw_row, ["productive"]))

    def _note_productive(self) -> None:
        """Record how `productive` was handled — the spec asks for it to be
        marked as annotation-derived whenever it is carried through."""
        if self.allow_productive:
            message = (
                "productive was carried through from Cell Ranger at your "
                "request. It is annotation-derived, not an assembly "
                "measurement — IMGT should be treated as the authority."
            )
        else:
            message = (
                "productive was left empty: it is annotation-derived, and "
                "carrying Cell Ranger's call through was not requested."
            )
        logger.info("%s: %s", self.format_id, message)
        self.warnings.append(message)

    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        if self.variant in _CONTIG_VARIANTS:
            return self._parse_contig_csv(files)
        return self._parse_airr_tsv(files)

    def _warn_skipped(self) -> None:
        """Surface every row that did not become a record, with its reason."""
        reasons = {
            "rows_without_contig_id": "had no contig_id",
            "rows_without_fasta_sequence": "name a contig absent from the FASTA",
            "rows_without_sequence": "had no sequence_id or sequence",
            "rows_without_barcode": "had no cell barcode and were not assigned an invented one",
            "fasta_records_without_annotation": "in the FASTA have no annotation row",
        }
        for key, reason in reasons.items():
            n = self.parse_report.get(key, 0)
            if n:
                self.warnings.append(f"Cell Ranger: {n} row(s) {reason}; left out.")

    def _parse_contig_csv(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        fasta_path = files.get("contig_fasta")
        csv_path = files.get("contig_annotations")
        if not fasta_path or not csv_path:
            raise SingleCellAdapterError(
                "Cell Ranger VDJ input requires both the contig FASTA and "
                "the contig annotations CSV"
            )

        sequences = read_fasta_dict(fasta_path)
        records: list[UnifiedRecord] = []
        report = {
            "fasta_records": len(sequences),
            "annotation_rows": 0,
            "rows_without_contig_id": 0,
            "rows_without_barcode": 0,
            "rows_without_fasta_sequence": 0,
        }
        self.parse_report = report

        annotated_ids: set[str] = set()
        with csv_path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            for raw_row in reader:
                report["annotation_rows"] += 1
                # Leakage stripping is applied for defense-at-the-source even
                # though this adapter only ever reads a fixed allowlist of
                # columns below; it also documents which columns are
                # intentionally never read (chain/v_gene/.../cdr3_nt).
                strip_leakage_fields(raw_row)
                contig_id = first_present(raw_row, ["contig_id"])
                if not contig_id:
                    report["rows_without_contig_id"] += 1
                    continue
                # The row as Cell Ranger wrote it, before any stripping, so
                # the dropped calls survive in source_annotations.tsv.
                self.record_source_annotation(
                    contig_id, raw_row, origin=csv_path.name
                )
                annotated_ids.add(contig_id)
                sequence = sequences.get(contig_id)
                if sequence is None:
                    report["rows_without_fasta_sequence"] += 1
                    continue
                # Never fall back to the contig id: that would make each
                # contig its own "cell".
                barcode = first_present(raw_row, ["barcode"])
                if not barcode:
                    report["rows_without_barcode"] += 1
                    continue
                is_cell = parse_bool(first_present(raw_row, ["is_cell"]))
                high_confidence = parse_bool(first_present(raw_row, ["high_confidence"]))
                records.append(
                    UnifiedRecord(
                        sequence_id=contig_id,
                        sequence=sequence,
                        cell_id=barcode,
                        umi_count=parse_int(first_present(raw_row, ["umis"])),
                        read_count=parse_int(first_present(raw_row, ["reads"])),
                        is_cell=is_cell,
                        high_confidence=high_confidence,
                        productive=self._productive(raw_row),
                    )
                )

        report["fasta_records_without_annotation"] = len(sequences.keys() - annotated_ids)
        report["records_written"] = len(records)
        if not records:
            raise SingleCellAdapterError(
                "No contigs could be matched between the annotations CSV and the FASTA"
            )
        self._warn_skipped()
        self._note_productive()
        return records

    def _parse_airr_tsv(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        tsv_path = files.get("airr_tsv")
        if not tsv_path:
            raise SingleCellAdapterError("Cell Ranger AIRR TSV input requires the TSV file")

        records: list[UnifiedRecord] = []
        report = {
            "airr_rows": 0,
            "rows_without_sequence": 0,
            "rows_without_barcode": 0,
        }
        self.parse_report = report
        with tsv_path.open(newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for raw_row in reader:
                report["airr_rows"] += 1
                sequence_id = first_present(raw_row, ["sequence_id"])
                sequence = first_present(raw_row, ["sequence"])
                if not sequence_id or not sequence:
                    report["rows_without_sequence"] += 1
                    continue
                self.record_source_annotation(
                    sequence_id, raw_row, origin=tsv_path.name
                )
                cell_id = first_present(raw_row, ["cell_id"])
                if not cell_id:
                    report["rows_without_barcode"] += 1
                    continue
                is_cell = parse_bool(first_present(raw_row, ["is_cell"]))
                high_confidence = parse_bool(first_present(raw_row, ["high_confidence"]))
                records.append(
                    UnifiedRecord(
                        sequence_id=sequence_id,
                        sequence=sequence,
                        cell_id=cell_id,
                        # CAREFUL — the spec table's parenthetical
                        # ("consensus_count (UMI), duplicate_count (reads)")
                        # is the wrong way round for real Cell Ranger output,
                        # so do not "fix" this to match it. Verified against
                        # sc5p_v2_hs_PBMC_1k contig AACTCCCAGGCTAGGT-1_contig_1:
                        # the annotations CSV says umis=79, reads=21711, and
                        # the AIRR TSV for that same contig says
                        # duplicate_count=79, consensus_count=21711. So
                        # duplicate_count is the UMI count and consensus_count
                        # is the read count. The regression test for this is
                        # that cellranger_vdj_filtered and cellranger_airr_tsv
                        # must produce byte-identical output for one sample.
                        umi_count=parse_int(
                            first_present(raw_row, ["umi_count", "duplicate_count"])
                        ),
                        read_count=parse_int(
                            first_present(raw_row, ["read_count", "reads", "consensus_count"])
                        ),
                        is_cell=is_cell,
                        # Cell Ranger writes airr_rearrangement.tsv from its
                        # filtered, high-confidence contigs and has no column
                        # for it, so the flag is left empty unless present.
                        high_confidence=high_confidence,
                        productive=self._productive(raw_row),
                    )
                )

        report["records_written"] = len(records)
        if not records:
            raise SingleCellAdapterError("No records found in the AIRR TSV file")
        self._warn_skipped()
        self._note_productive()
        return records
