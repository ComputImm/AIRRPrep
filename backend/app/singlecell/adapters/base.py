# app/singlecell/adapters/base.py
"""
Adapter interface every single-cell input format implements.

Each adapter converts its own vendor/format-specific files into the same
list[UnifiedRecord] — the pipeline downstream (validation, FASTA/TSV
generation) never needs to know which format it came from.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, ClassVar

from app.singlecell.models import UnifiedRecord


class SingleCellAdapter(ABC):
    """Base class for a single-cell input format adapter."""

    format_id: ClassVar[str]

    #: Extra job stages this adapter runs before the shared Parse stage.
    #: tasks.py turns these into their own progress steps — without it a
    #: multi-hour TRUST4 assembly would sit invisibly inside "Parse".
    pre_stages: ClassVar[tuple[str, ...]] = ()

    def __init__(self):
        # Adapters may append non-fatal, per-record issues here (e.g. a
        # TRUST4 row that couldn't be matched to a contig) — tasks.py surfaces
        # these alongside validator.py's warnings in the job doc.
        self.warnings: list[str] = []
        # Counts an adapter records while parsing (rows read, rows skipped,
        # contigs left without a barcode, ...) so a run can be audited
        # afterwards; tasks.py stores them on the job and in provenance.json.
        self.parse_report: dict[str, int] = {}
        # Every field the source carried for a record, keyed by the source's
        # own sequence_id -- including the V(D)J calls, junctions and CDR3s
        # the normalized output deliberately drops. fasta_generator writes
        # this out as source_annotations.tsv, so the omitted annotations
        # survive the run rather than only being traceable to an input file
        # that may since have expired. Adapters fill it through
        # record_source_annotation().
        self.source_annotations: dict[str, dict[str, str]] = {}
        # Column order, first-seen, so the sidecar reproduces the source's own
        # layout instead of an alphabetical one.
        self.source_annotation_fields: list[str] = []
        # Which uploaded file(s) the rows above were read from; goes into
        # provenance.json next to the sidecar's checksum.
        self.source_annotation_origin: list[str] = []
        # Set by tasks.py; called with a pre_stage name once that stage has
        # finished, so job progress advances mid-parse.
        self.on_stage_complete: Callable[[str], None] | None = None

    def _stage_done(self, stage: str) -> None:
        if self.on_stage_complete is not None:
            self.on_stage_complete(stage)

    def _adopt_source_annotations(self, inner: "SingleCellAdapter") -> None:
        """Take over the source annotations of a delegated adapter.

        The raw-read formats assemble first and then parse the result with
        Trust4Adapter; the sidecar has to follow the records out.
        """
        self.source_annotations = inner.source_annotations
        self.source_annotation_fields = inner.source_annotation_fields
        self.source_annotation_origin = inner.source_annotation_origin

    def record_source_annotation(
        self, sequence_id: str, row: dict, *, origin: str | None = None
    ) -> None:
        """Keep one source row verbatim, keyed by the source's sequence_id.

        Called with the raw row exactly as read, before any leakage
        stripping, so nothing the input carried is lost. A second call for
        the same identifier merges non-empty values rather than replacing the
        row, because a format may describe one record in two files (TRUST4's
        barcode report and its AIRR table, for example).
        """
        if not sequence_id:
            return
        if origin and origin not in self.source_annotation_origin:
            self.source_annotation_origin.append(origin)
        existing = self.source_annotations.setdefault(sequence_id, {})
        for key, value in row.items():
            if key is None or key == "sequence_id":
                continue
            if key not in self.source_annotation_fields:
                self.source_annotation_fields.append(key)
            text = "" if value is None else str(value)
            if text or key not in existing:
                existing[key] = text

    @abstractmethod
    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        """
        Convert the given role -> file path mapping (roles as defined by the
        adapter's FormatSpec in detector.py) into unified records.

        Raises SingleCellAdapterError (or a subclass) on any input problem.
        """
        raise NotImplementedError

    def validate(self, files: dict[str, Path]) -> tuple[int | None, list[str]]:
        """
        Cheap pre-flight check for the /validate endpoint, returning
        (record_count_estimate, warnings).

        The default runs a full parse + record validation, which is exactly
        right for adapters that just read files. Adapters whose parse() is
        expensive (anything that shells out to TRUST4) override this so
        validation stays a fast request rather than a full assembly.
        """
        from app.singlecell.validator import validate_records

        records, warnings = validate_records(self.parse(files))
        return len(records), [*self.warnings, *warnings]
