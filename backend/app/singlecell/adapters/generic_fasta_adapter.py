# app/singlecell/adapters/generic_fasta_adapter.py
"""
Generic FASTA adapter — the escape hatch for sequences that come from no
recognised pipeline.

The user MUST declare how the cell barcode is recovered, via exactly one of:

  * a barcode mapping file (columns: sequence_id, cell_id, umi_count,
    read_count), joined by exact sequence_id match; or
  * a regular expression with one capture group, applied to the FASTA header.

If neither is supplied, or if any single sequence has no recoverable barcode,
this adapter fails. That is deliberate and required by the spec: without a
real barcode there is no single-cell resolution, and quietly substituting the
sequence_id would manufacture a dataset where every sequence looks like its
own cell — silently turning N contigs into N fake "cells" and corrupting every
downstream per-cell statistic. A hard error is the only safe behaviour.
"""

import csv
import re
from pathlib import Path

from app.singlecell.adapters._util import (
    first_present,
    parse_int,
    read_fasta_with_headers,
)
from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import UnifiedRecord
from app.singlecell.validator import strip_leakage_fields

#: How many unresolved sequence ids to name in the error before truncating.
_MAX_REPORTED = 5


class GenericFastaAdapter(SingleCellAdapter):
    format_id = "generic_fasta"

    def __init__(self, barcode_header_regex: str | None = None):
        super().__init__()
        self.barcode_header_regex = (barcode_header_regex or "").strip() or None

    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        fasta_path = files.get("fasta")
        if not fasta_path:
            raise SingleCellAdapterError("Generic FASTA input requires a FASTA file")

        barcode_map_path = files.get("barcode_map")
        if not barcode_map_path and not self.barcode_header_regex:
            raise SingleCellAdapterError(
                "Generic FASTA requires a way to recover the cell barcode: "
                "upload a barcode mapping file (sequence_id, cell_id, "
                "umi_count, read_count), or supply a header regex with one "
                "capture group. Without one, cell_id cannot be recovered and "
                "single-cell resolution cannot be guaranteed."
            )

        pattern = self._compile_regex()
        entries = read_fasta_with_headers(fasta_path)
        if not entries:
            raise SingleCellAdapterError("No sequences found in the FASTA file")

        barcode_map = self._read_barcode_map(barcode_map_path)
        raw_map_rows = self._read_raw_map_rows(barcode_map_path)

        records: list[UnifiedRecord] = []
        unresolved: list[str] = []

        for sequence_id, header, sequence in entries:
            mapped = barcode_map.get(sequence_id, {})
            # A bare FASTA carries its annotations, if any, in the header
            # itself; the mapping file may carry more. Both are kept.
            self.record_source_annotation(
                sequence_id,
                {"fasta_header": header, **raw_map_rows.get(sequence_id, {})},
                origin=fasta_path.name,
            )
            cell_id = mapped.get("cell_id")

            # The mapping file wins; the regex is the fallback, so a file that
            # covers only some sequences can be topped up from the headers.
            if not cell_id and pattern is not None:
                match = pattern.search(header)
                if match:
                    cell_id = match.group(1) if match.groups() else match.group(0)

            if not cell_id:
                unresolved.append(sequence_id)
                continue

            records.append(
                UnifiedRecord(
                    sequence_id=sequence_id,
                    sequence=sequence,
                    cell_id=cell_id,
                    umi_count=parse_int(mapped.get("umi_count")),
                    read_count=parse_int(mapped.get("read_count")),
                    # A bare FASTA carries no cell calling, so these are
                    # left empty rather than asserted.
                    is_cell=None,
                    high_confidence=None,
                    # Never available from a bare FASTA, and annotation-derived
                    # in any case.
                    productive=None,
                )
            )

        self.parse_report = {
            "fasta_records": len(entries),
            "barcode_map_rows": len(barcode_map),
            "barcodes_from_map": sum(
                1 for sid, _, _ in entries if barcode_map.get(sid, {}).get("cell_id")
            ),
            "records_without_barcode": len(unresolved),
            "records_written": len(records),
        }

        if unresolved:
            shown = ", ".join(unresolved[:_MAX_REPORTED])
            more = (
                f" (and {len(unresolved) - _MAX_REPORTED} more)"
                if len(unresolved) > _MAX_REPORTED
                else ""
            )
            raise SingleCellAdapterError(
                f"No barcode could be recovered for {len(unresolved)} of "
                f"{len(entries)} sequences: {shown}{more}. Single-cell "
                "resolution cannot be guaranteed, so the run was stopped "
                "rather than inventing a cell_id. Check that the mapping "
                "file covers every sequence_id, or that the header regex "
                "matches every header."
            )

        return records

    def _compile_regex(self) -> re.Pattern | None:
        if not self.barcode_header_regex:
            return None
        try:
            return re.compile(self.barcode_header_regex)
        except re.error as e:
            raise SingleCellAdapterError(
                f"The barcode header regex is not valid: {e}"
            ) from e

    @staticmethod
    def _read_raw_map_rows(path: Path | None) -> dict[str, dict]:
        """The mapping file's rows verbatim, keyed by sequence_id.

        _read_barcode_map keeps only the four columns the adapter uses; this
        keeps everything, so a mapping file that also carries the user's own
        annotation columns does not lose them.
        """
        if not path:
            return {}
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows: dict[str, dict] = {}
        with path.open(newline="") as fh:
            for raw_row in csv.DictReader(fh, delimiter=delimiter):
                sequence_id = first_present(raw_row, ["sequence_id"])
                if sequence_id:
                    rows[sequence_id] = dict(raw_row)
        return rows

    @staticmethod
    def _read_barcode_map(path: Path | None) -> dict[str, dict]:
        if not path:
            return {}
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        result: dict[str, dict] = {}
        with path.open(newline="") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            for raw_row in reader:
                row = strip_leakage_fields(raw_row)
                sequence_id = first_present(row, ["sequence_id"])
                if not sequence_id:
                    continue
                result[sequence_id] = {
                    "cell_id": first_present(row, ["cell_id"]),
                    "umi_count": first_present(row, ["umi_count"]),
                    "read_count": first_present(row, ["read_count"]),
                }
        return result
