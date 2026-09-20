# app/singlecell/models.py
"""
Shared data model for the single-cell preprocessing module.

UnifiedRecord is the ONE internal shape every adapter converts its own
format into. It deliberately excludes any annotation-derived field
(v_call/d_call/j_call/c_call, junction/junction_aa, *_identity, ...) — those
must be left for IMGT to infer downstream. See validator.strip_leakage_fields
for where those fields get stripped out of raw adapter input.
"""

from typing import Literal

from pydantic import BaseModel, Field

FormatId = Literal[
    "cellranger_vdj_all",
    "cellranger_vdj_filtered",
    "cellranger_airr_tsv",
    "trust4",
    "fastq_10x",
    "bam_10x",
    "generic_fasta",
]


class UnifiedRecord(BaseModel):
    """The one normalized internal record every adapter produces.

    This is AIRRPrep's own schema, not an AIRR Community Rearrangement record.
    Null rule: a value the source does not carry stays None (an empty TSV
    cell) rather than being defaulted. `sequence_id` is always the source's
    own record identifier, unchanged, so every output row can be joined back
    to the uploaded file it came from (see provenance.json).
    """

    sequence_id: str
    sequence: str
    cell_id: str
    umi_count: int | None = None
    read_count: int | None = None
    is_cell: bool | None = None
    high_confidence: bool | None = None
    productive: bool | None = None


# Formats whose adapter has to run a TRUST4 assembly before it can parse
# anything — the two that take raw reads rather than assembled contigs.
TRUST4_ASSEMBLY_FORMATS = frozenset({"fastq_10x", "bam_10x"})

# 10x read-1 layouts. TRUST4 is told which slice of R1 is the cell barcode and
# which is the UMI (--readFormat bc:start:end,um:start:end); everything else about the
# chemistry is irrelevant to assembly. Ranges are inclusive 0-based, matching
# TRUST4's own convention.
CHEMISTRY_PRESETS: dict[str, dict] = {
    "10x_v2": {
        "label": "10x v2 (16 bp barcode + 10 bp UMI)",
        "barcode_range": (0, 15),
        "umi_range": (16, 25),
    },
    "10x_v3": {
        "label": "10x v3 (16 bp barcode + 12 bp UMI)",
        "barcode_range": (0, 15),
        "umi_range": (16, 27),
    },
    "custom": {
        "label": "Custom ranges",
        "barcode_range": None,
        "umi_range": None,
    },
}


class Trust4Options(BaseModel):
    """User-controllable knobs for a TRUST4 assembly run.

    Only meaningful for the formats in TRUST4_ASSEMBLY_FORMATS; ignored for
    inputs that are already assembled.
    """

    species: Literal["human", "mouse"] = "human"
    chemistry: Literal["10x_v2", "10x_v3", "custom"] = "10x_v2"
    #: BAM input only. Convert the BAM to FASTQ with samtools and use TRUST4's
    #: FASTQ path instead of handing the BAM to bam-extractor. Needed whenever
    #: the BAM is not aligned to a reference genome, because bam-extractor
    #: locates reads by genomic coordinate while the FASTQ path screens them
    #: by sequence and does not care what they were aligned to.
    bam_extract_with_samtools: bool = False
    # Only read when chemistry == "custom"; inclusive 0-based offsets into R1.
    barcode_start: int = 0
    barcode_end: int = 15
    umi_start: int = 16
    umi_end: int = 25

    def resolved_ranges(self) -> tuple[tuple[int, int], tuple[int, int]]:
        preset = CHEMISTRY_PRESETS[self.chemistry]
        barcode = preset["barcode_range"] or (self.barcode_start, self.barcode_end)
        umi = preset["umi_range"] or (self.umi_start, self.umi_end)
        return barcode, umi


class Trust4SpeciesInfo(BaseModel):
    id: str
    label: str
    available: bool
    problems: list[str] = Field(default_factory=list)


class Trust4ChemistryInfo(BaseModel):
    id: str
    label: str
    barcode_range: tuple[int, int] | None = None
    umi_range: tuple[int, int] | None = None


class Trust4Status(BaseModel):
    """What the server can actually do with raw-read input right now."""

    available: bool
    binary: str
    problems: list[str] = Field(default_factory=list)
    species: list[Trust4SpeciesInfo] = Field(default_factory=list)
    chemistries: list[Trust4ChemistryInfo] = Field(default_factory=list)
    default_species: str = "human"
    threads: int = 1
    barcode_whitelist_configured: bool = False


class MatchedFile(BaseModel):
    role: str
    file_id: str
    filename: str


class MissingFile(BaseModel):
    role: str
    description: str
    required: bool = True


class DetectionResult(BaseModel):
    format_id: FormatId | None = None
    label: str | None = None
    matched_files: list[MatchedFile] = Field(default_factory=list)
    missing_files: list[MissingFile] = Field(default_factory=list)
    ready: bool = False
    ambiguous_format_ids: list[str] = Field(default_factory=list)
    requires_trust4: bool = False
    trust4_available: bool = False
