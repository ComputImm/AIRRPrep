# app/singlecell/detector.py
"""
Detects which single-cell input format a set of uploaded files represents,
and reports which required/optional companion files are matched or missing.

This mirrors the *shape* of app/pipeline/planner.py's file-set inspection,
but is far simpler: single-cell adapters are chosen by detection, not
composed step-by-step, so there's no step graph here — just "which one
FormatSpec does this file set satisfy".
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.core.file_store import StoredFile
from app.singlecell.models import DetectionResult, MatchedFile, MissingFile


@dataclass
class Role:
    """One file this format needs, matched by filename hint + extension."""

    name: str
    description: str
    suffixes: tuple[str, ...]
    name_hints: tuple[str, ...] = ()
    required: bool = True

    def matches(self, filename: str) -> bool:
        lower = filename.lower()
        # A trailing .gz is transparent: 10x FASTQs are essentially always
        # delivered as *.fastq.gz, and both TRUST4 and BioPython read them
        # compressed, so match on the extension underneath it.
        if lower.endswith(".gz"):
            lower = lower[: -len(".gz")]
        if Path(lower).suffix not in self.suffixes:
            return False
        if not self.name_hints:
            return True
        return any(hint in lower for hint in self.name_hints)


@dataclass
class FormatSpec:
    format_id: str
    label: str
    roles: list[Role]
    needs_trust4: bool = False

    @property
    def required_roles(self) -> list[Role]:
        return [r for r in self.roles if r.required]

    @property
    def optional_roles(self) -> list[Role]:
        return [r for r in self.roles if not r.required]


# Ordered most-specific-first: when several specs are fully satisfied by the
# same file set (e.g. a generic FASTA sitting next to a Cell Ranger CSV), the
# first fully-matched spec in this list wins; the rest are reported as
# ambiguous alternates rather than silently dropped.
FORMAT_SPECS: list[FormatSpec] = [
    FormatSpec(
        format_id="cellranger_vdj_all",
        label="Cell Ranger VDJ (all contigs)",
        roles=[
            Role(
                "contig_fasta",
                "all_contig.fasta",
                (".fasta", ".fa"),
                ("all_contig",),
            ),
            Role(
                "contig_annotations",
                "all_contig_annotations.csv",
                (".csv",),
                ("all_contig_annotations",),
            ),
        ],
    ),
    FormatSpec(
        format_id="cellranger_vdj_filtered",
        label="Cell Ranger filtered VDJ",
        roles=[
            Role(
                "contig_fasta",
                "filtered_contig.fasta",
                (".fasta", ".fa"),
                ("filtered_contig",),
            ),
            Role(
                "contig_annotations",
                "filtered_contig_annotations.csv",
                (".csv",),
                ("filtered_contig_annotations",),
            ),
        ],
    ),
    FormatSpec(
        format_id="cellranger_airr_tsv",
        label="Cell Ranger AIRR TSV",
        roles=[
            Role("airr_tsv", "AIRR rearrangement TSV", (".tsv",), ("airr",)),
        ],
    ),
    FormatSpec(
        format_id="trust4",
        label="TRUST4 output",
        roles=[
            Role(
                "annot_fasta",
                "*_annot.fa",
                (".fa", ".fasta"),
                ("_annot", "annot"),
            ),
            Role(
                "barcode_report",
                "*_barcode_report.tsv",
                (".tsv",),
                ("barcode_report",),
            ),
        ],
    ),
    FormatSpec(
        format_id="fastq_10x",
        label="Raw 10x FASTQ (requires TRUST4)",
        roles=[
            Role("r1_fastq", "R1 FASTQ", (".fastq", ".fq"), ("r1",)),
            Role("r2_fastq", "R2 FASTQ", (".fastq", ".fq"), ("r2",)),
        ],
        needs_trust4=True,
    ),
    FormatSpec(
        format_id="bam_10x",
        label="10x BAM (requires TRUST4)",
        roles=[Role("bam", "10x BAM file", (".bam",))],
        needs_trust4=True,
    ),
    FormatSpec(
        format_id="generic_fasta",
        label="Generic FASTA",
        roles=[
            Role("fasta", "Sequence FASTA", (".fasta", ".fa", ".fas")),
            Role(
                "barcode_map",
                "Optional barcode mapping file",
                (".csv", ".tsv"),
                required=False,
            ),
        ],
    ),
]


@dataclass
class _Match:
    spec: FormatSpec
    matched: dict[str, StoredFile] = field(default_factory=dict)


def _match_spec(spec: FormatSpec, files: list[StoredFile]) -> _Match:
    match = _Match(spec=spec)
    remaining = list(files)
    for role in spec.roles:
        for stored in remaining:
            if role.matches(stored.original_name):
                match.matched[role.name] = stored
                remaining.remove(stored)
                break
    return match


def _is_fully_matched(match: _Match) -> bool:
    return all(role.name in match.matched for role in match.spec.required_roles)


def detect_adapter(
    files: list[StoredFile], trust4_available: bool = False
) -> DetectionResult:
    matches = [_match_spec(spec, files) for spec in FORMAT_SPECS]
    fully_matched = [m for m in matches if _is_fully_matched(m)]

    if not fully_matched:
        # Report the closest candidate (most roles matched) so the UI can
        # show a helpful "you're missing X" checklist instead of nothing.
        best = max(matches, key=lambda m: len(m.matched), default=None)
        if best is None or not best.matched:
            return DetectionResult(ready=False)
        return DetectionResult(
            format_id=None,
            label=best.spec.label,
            matched_files=[
                MatchedFile(role=role, file_id=f.file_id, filename=f.original_name)
                for role, f in best.matched.items()
            ],
            missing_files=[
                MissingFile(role=r.name, description=r.description, required=True)
                for r in best.spec.required_roles
                if r.name not in best.matched
            ],
            ready=False,
            requires_trust4=best.spec.needs_trust4,
            trust4_available=trust4_available,
        )

    chosen = fully_matched[0]
    ambiguous = [m.spec.format_id for m in fully_matched[1:]]

    missing_optional = [
        MissingFile(role=r.name, description=r.description, required=False)
        for r in chosen.spec.optional_roles
        if r.name not in chosen.matched
    ]

    return DetectionResult(
        format_id=chosen.spec.format_id,  # type: ignore[arg-type]
        label=chosen.spec.label,
        matched_files=[
            MatchedFile(role=role, file_id=f.file_id, filename=f.original_name)
            for role, f in chosen.matched.items()
        ],
        missing_files=missing_optional,
        ready=True,
        ambiguous_format_ids=ambiguous,
        requires_trust4=chosen.spec.needs_trust4,
        trust4_available=trust4_available,
    )


def get_format_spec(format_id: str) -> FormatSpec:
    for spec in FORMAT_SPECS:
        if spec.format_id == format_id:
            return spec
    raise ValueError(f"Unknown single-cell format_id: {format_id}")
