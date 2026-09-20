# app/singlecell/adapters/bam_adapter.py
"""
10x BAM adapter — hands the BAM straight to TRUST4 and parses what comes
back with Trust4Adapter, the same as FastqAdapter does.

No pysam here on purpose: TRUST4's own bam-extractor already reads the
per-read CB/UB tags, so pulling the reads out in Python first would only
duplicate that work (and add a heavyweight build dependency) for no gain.
"""

from pathlib import Path

from app.singlecell.adapters._util import (
    read_bam_reference_names,
    read_reference_chromosomes,
)
from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import Trust4Options, UnifiedRecord
from app.singlecell.trust4_runner import Trust4Runner


class BamAdapter(SingleCellAdapter):
    format_id = "bam_10x"
    pre_stages = ("Assemble (TRUST4)",)

    def __init__(
        self,
        options: Trust4Options | None = None,
        runner: Trust4Runner | None = None,
        work_dir: Path | None = None,
    ):
        super().__init__()
        self.options = options or Trust4Options()
        self.runner = runner or Trust4Runner(species=self.options.species)
        self.work_dir = work_dir

    def _require_bam(self, files: dict[str, Path]) -> Path:
        bam = files.get("bam")
        if not bam:
            raise SingleCellAdapterError("10x BAM input requires a .bam file")
        return bam

    def _check_genome_aligned(self, bam: Path) -> None:
        """Reject a BAM that is not aligned to a reference genome.

        TRUST4 locates candidate reads by the genomic coordinates in its
        bcrtcr reference, so it needs the BAM's @SQ entries to be the
        chromosomes those coordinates refer to. Given anything else it dies
        deep inside bam-extractor with `unknown genome name chr1` (chr1 being
        merely the first locus in the reference file), which says nothing
        about the real problem. Catching it here turns a mid-assembly crash
        into an answer.

        The common way to hit this is uploading Cell Ranger's
        `all_contig.bam`: it carries the right CB/UB tags, but its @SQ
        entries are the assembled contigs, not chromosomes.
        """
        try:
            ref_names = read_bam_reference_names(bam)
        except Exception as e:
            raise SingleCellAdapterError(f"Could not read the BAM header: {e}") from e

        if not ref_names:
            raise SingleCellAdapterError(
                "This BAM declares no reference sequences, so TRUST4 cannot "
                "locate V(D)J reads in it."
            )

        vdj_ref = Path(self.runner.vdj_ref_fasta)
        if not vdj_ref.is_file():
            return  # availability is reported separately; nothing to compare against

        chromosomes = read_reference_chromosomes(vdj_ref)
        if chromosomes & set(ref_names):
            return

        sample = ", ".join(ref_names[:3])
        raise SingleCellAdapterError(
            "This BAM is not aligned to a reference genome, so TRUST4 cannot "
            f"use it. Its reference sequences look like: {sample}. TRUST4 "
            "needs a genome-aligned BAM whose references are chromosomes "
            "(chr1, chr2, chr14, …), because it finds V(D)J reads by genomic "
            "coordinate. Cell Ranger's all_contig.bam is aligned to the "
            "assembled contigs, not the genome, so it cannot be used here — "
            "upload possorted_genome_bam.bam (or an equivalent genome "
            "alignment) instead. If all you have is all_contig.bam, use the "
            "Cell Ranger VDJ workflow with all_contig.fasta plus its "
            "annotations CSV, which needs no assembly at all. To assemble "
            "from this BAM anyway, switch on \"Extract reads with samtools "
            "first\" — that route reads the file with samtools instead of "
            "bam-extractor, so the alignment coordinates stop mattering."
        )

    def validate(self, files: dict[str, Path]) -> tuple[int | None, list[str]]:
        """Pre-flight only — assembly happens in the job, not the request."""
        bam = self._require_bam(files)
        self.runner.require_available()
        if not bam.is_file():
            raise SingleCellAdapterError("BAM file is missing on disk")

        if self.options.bam_extract_with_samtools:
            # This route reads the BAM with samtools rather than handing it to
            # bam-extractor, so how it was aligned no longer matters and the
            # genome check does not apply.
            self.runner.require_samtools()
            return None, [
                "Reads will be extracted from the BAM with samtools first, "
                "then assembled through TRUST4's FASTQ path. Cell barcodes "
                "and UMIs are carried across from the CB/UB tags.",
                "Record count is only known after assembly.",
            ]

        self._check_genome_aligned(bam)
        return None, [
            "Record count is only known after assembly: TRUST4 will run when "
            f"the job starts, using the {self.options.species} reference and "
            "reading cell barcodes/UMIs from the BAM's CB/UB tags."
        ]

    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        bam = self._require_bam(files)
        out_dir = (self.work_dir or Path.cwd()) / "trust4"

        if self.options.bam_extract_with_samtools:
            trust4_outputs = self.runner.run_bam_via_fastq(bam, out_dir)
        else:
            # Re-checked here, not only in validate(): a job can be started
            # from an API client that never called /validate.
            self._check_genome_aligned(bam)
            trust4_outputs = self.runner.run_bam(bam, out_dir)
        self._stage_done(self.pre_stages[0])

        trust4_adapter = Trust4Adapter()
        records = trust4_adapter.parse(trust4_outputs)
        self.warnings.extend(trust4_adapter.warnings)
        self._adopt_source_annotations(trust4_adapter)
        # Read-level tag counts (samtools route only) sit beside the
        # contig-level ones, so a run shows where cell identity was kept.
        self.parse_report = {**self.runner.tag_stats, **trust4_adapter.parse_report}
        return records
