# app/singlecell/adapters/trust4_adapter.py
"""
TRUST4 output adapter — turns TRUST4's `*_annot.fa` plus the file that maps
each contig to its cell into unified records.

Uploaded directly, the pair is `*_annot.fa` + `*_barcode_report.tsv`. After an
assembly run by FastqAdapter/BamAdapter the runner also hands over
TRUST4's per-cell AIRR table (`*_barcode_airr.tsv`), whose `cell_id` column is
used as a second source for the same contig -> cell mapping.

**A contig's cell is never invented.** Only contigs that TRUST4 itself reports
as a chain of a cell are written. annot.fa also holds every other assembled
contig (partial or low-support fragments TRUST4 does not assign as a cell's
chain); those are left out and counted, and a run
in which no contig can be placed in a cell fails. The contig identifier is
never substituted for a missing cell identifier: doing that turns N contigs
into N artificial "cells" and corrupts every per-cell statistic downstream.

Parsing the barcode report does not depend on a fixed position inside the
packed chain fields. TRUST4 has changed that layout between releases
(`V,D,J,C,cdr3_nt,cdr3_aa,read_cnt,consensus_id` in older ones, with
`CDR3_germline_similarity,consensus_full_length` appended in 1.0.x and
later), so the consensus id is found as the token that names a contig
actually present in annot.fa, and the read count is the integer immediately
before it. A layout change therefore shows up as counted unmatched contigs,
never as silently misassigned ones.

Every count needed to audit the parse is kept in `parse_report`.
"""

import csv
from pathlib import Path

from app.singlecell.adapters._util import (
    first_present,
    parse_int,
    read_fasta_with_headers,
)
from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import UnifiedRecord

_BARCODE_KEYS = ["#barcode", "barcode", "cell_barcode"]
_CHAIN_KEY_PREFIXES = ("chain", "secondary_chain")
_NO_CHAIN_MARKERS = {"*", "-", ""}
#: How many offending ids to name in a message before truncating.
_MAX_REPORTED = 5


class Trust4Adapter(SingleCellAdapter):
    format_id = "trust4"

    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        annot_path = files.get("annot_fasta")
        report_path = files.get("barcode_report")
        airr_path = files.get("airr_tsv")
        if not annot_path or not (report_path or airr_path):
            raise SingleCellAdapterError(
                "TRUST4 input requires the *_annot.fa file together with "
                "*_barcode_report.tsv, which maps each contig to its cell barcode"
            )

        # annot.fa's header carries TRUST4's own per-contig annotation (the
        # V/D/J/C assignment and CDR3), which the normalized record drops;
        # it is kept verbatim in source_annotations.tsv.
        entries = read_fasta_with_headers(annot_path)
        sequences = {contig_id: sequence for contig_id, _, sequence in entries}
        if not sequences:
            raise SingleCellAdapterError("No sequences found in the TRUST4 annot FASTA")
        for contig_id, header, _ in entries:
            self.record_source_annotation(
                contig_id, {"annot_header": header}, origin=annot_path.name
            )

        report = {
            "annot_contigs": len(sequences),
            "report_rows": 0,
            "report_rows_without_barcode": 0,
            "report_chain_fields_parsed": 0,
            "report_chain_fields_unmatched": 0,
            "airr_rows": 0,
            "airr_rows_with_cell_id": 0,
            "duplicate_mappings": 0,
            "conflicting_mappings": 0,
            "contigs_not_in_cell_report": 0,
            "records_written": 0,
            "cells": 0,
        }
        self.parse_report = report

        contig_meta: dict[str, dict] = {}
        conflicts: list[str] = []
        if report_path:
            self._read_barcode_report(report_path, sequences, contig_meta, conflicts, report)
        if airr_path:
            self._read_airr_cells(airr_path, sequences, contig_meta, conflicts, report)

        if conflicts:
            shown = ", ".join(conflicts[:_MAX_REPORTED])
            raise SingleCellAdapterError(
                f"{len(conflicts)} TRUST4 contig(s) are assigned to more than one "
                f"cell barcode ({shown}). The cell of those contigs is ambiguous, "
                "so the run was stopped rather than choosing one."
            )

        records: list[UnifiedRecord] = []
        unplaced: list[str] = []
        for contig_id, sequence in sequences.items():
            meta = contig_meta.get(contig_id)
            if meta is None:
                unplaced.append(contig_id)
                continue
            records.append(
                UnifiedRecord(
                    sequence_id=contig_id,
                    sequence=sequence,
                    cell_id=meta["cell_id"],
                    # TRUST4 reports read support per chain, not a UMI count.
                    umi_count=None,
                    read_count=meta.get("read_count"),
                    # TRUST4 does not make Cell Ranger's cell / confidence
                    # calls, so these stay empty rather than being asserted.
                    is_cell=None,
                    high_confidence=None,
                    productive=None,
                )
            )

        report["contigs_not_in_cell_report"] = len(unplaced)
        report["records_written"] = len(records)
        report["cells"] = len({r.cell_id for r in records})

        if not records:
            raise SingleCellAdapterError(
                f"None of the {len(sequences)} TRUST4 contigs could be assigned to "
                "a cell barcode. Check that the barcode report (or AIRR table) "
                "comes from the same TRUST4 run as the annot.fa file and that "
                "TRUST4 was run in barcode mode; single-cell output cannot be "
                "produced without cell barcodes."
            )
        if unplaced:
            shown = ", ".join(unplaced[:_MAX_REPORTED])
            self.warnings.append(
                f"TRUST4: {len(unplaced)} of {len(sequences)} assembled contigs are "
                f"not reported by TRUST4 as a chain of any cell and were left out "
                f"(e.g. {shown}). No contig was assigned an invented cell."
            )
        return records

    def _assign(self, contig_id, cell_id, read_count, contig_meta, conflicts, report):
        existing = contig_meta.get(contig_id)
        if existing is None:
            contig_meta[contig_id] = {"cell_id": cell_id, "read_count": read_count}
            return
        if existing["cell_id"] != cell_id:
            report["conflicting_mappings"] += 1
            conflicts.append(contig_id)
            return
        report["duplicate_mappings"] += 1
        if existing.get("read_count") is None and read_count is not None:
            existing["read_count"] = read_count

    def _read_barcode_report(self, path, sequences, contig_meta, conflicts, report):
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for raw_row in reader:
                report["report_rows"] += 1
                barcode = first_present(raw_row, _BARCODE_KEYS)
                if not barcode:
                    report["report_rows_without_barcode"] += 1
                    continue
                for key, value in raw_row.items():
                    if not key or not value:
                        continue
                    if not key.lower().startswith(_CHAIN_KEY_PREFIXES):
                        continue
                    if value.strip() in _NO_CHAIN_MARKERS:
                        continue  # "*": this cell has no such chain, not a parse failure
                    parsed = self._parse_chain_field(value, sequences)
                    if parsed is None:
                        report["report_chain_fields_unmatched"] += 1
                        continue
                    report["report_chain_fields_parsed"] += 1
                    contig_id, read_count = parsed
                    # The packed chain field holds TRUST4's V/D/J/C and CDR3
                    # call for this contig; keep the row it came from.
                    self.record_source_annotation(
                        contig_id,
                        {f"barcode_report.{k}": v for k, v in raw_row.items() if k},
                        origin=path.name,
                    )
                    self._assign(contig_id, barcode, read_count, contig_meta, conflicts, report)

        if report["report_chain_fields_unmatched"]:
            self.warnings.append(
                f"TRUST4: {report['report_chain_fields_unmatched']} chain field(s) in "
                "the barcode report name no contig present in annot.fa."
            )

    def _read_airr_cells(self, path, sequences, contig_meta, conflicts, report):
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for raw_row in reader:
                report["airr_rows"] += 1
                sequence_id = first_present(raw_row, ["sequence_id"])
                cell_id = first_present(raw_row, ["cell_id"])
                if not sequence_id or not cell_id or sequence_id not in sequences:
                    continue
                report["airr_rows_with_cell_id"] += 1
                self.record_source_annotation(
                    sequence_id,
                    {f"barcode_airr.{k}": v for k, v in raw_row.items() if k},
                    origin=path.name,
                )
                self._assign(sequence_id, cell_id, None, contig_meta, conflicts, report)

    @staticmethod
    def _parse_chain_field(
        value: str, sequences: dict[str, str]
    ) -> tuple[str, int | None] | None:
        """
        Return (consensus_id, read_count) for one packed chain field, or None
        when no token of it names a contig present in annot.fa.

        The consensus id is located by membership in annot.fa rather than by
        position, and the read count is the token immediately before it.
        """
        parts = [p.strip() for p in value.split(",")]
        for i, token in enumerate(parts):
            if token in sequences:
                read_count = parse_int(parts[i - 1]) if i > 0 else None
                return token, read_count
        return None
