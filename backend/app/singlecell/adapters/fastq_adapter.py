# app/singlecell/adapters/fastq_adapter.py
"""
Raw 10x FASTQ adapter. Does not parse sequences itself — composes
Trust4Runner (assembly) + Trust4Adapter (parsing the resulting output),
so there is exactly one place that knows how to read TRUST4 output.

R1 is treated as the barcode/UMI read and R2 as the cDNA read, per the 10x
layout; which slice of R1 is the barcode vs the UMI comes from the chemistry
preset in Trust4Options.
"""

from pathlib import Path

from app.singlecell.adapters.base import SingleCellAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.errors import SingleCellAdapterError
from app.singlecell.models import Trust4Options, UnifiedRecord
from app.singlecell.trust4_runner import Trust4Runner

# FASTQ suffixes we accept, before any .gz — TRUST4 reads gzipped input fine.
_FASTQ_SUFFIXES = (".fastq", ".fq")


class FastqAdapter(SingleCellAdapter):
    format_id = "fastq_10x"
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
        # Assembly output lands next to the job's other files rather than in
        # /tmp: TRUST4 intermediates are large, and keeping them in the job
        # workspace means they're cleaned up with the job.
        self.work_dir = work_dir

    def _require_pair(self, files: dict[str, Path]) -> tuple[Path, Path]:
        r1 = files.get("r1_fastq")
        r2 = files.get("r2_fastq")
        if not r1 or not r2:
            raise SingleCellAdapterError(
                "Raw 10x FASTQ input requires both R1 and R2 files"
            )
        return r1, r2

    def validate(self, files: dict[str, Path]) -> tuple[int | None, list[str]]:
        """
        Pre-flight only — never assembles. A full parse here would run a
        multi-hour TRUST4 job inside an HTTP request.
        """
        r1, r2 = self._require_pair(files)
        self.runner.require_available()

        warnings: list[str] = []
        for role, path in (("R1", r1), ("R2", r2)):
            if not path.is_file():
                raise SingleCellAdapterError(f"{role} file is missing on disk")
            name = path.name.lower().removesuffix(".gz")
            if not name.endswith(_FASTQ_SUFFIXES):
                warnings.append(
                    f"{role} ({path.name}) does not look like a FASTQ file"
                )

        barcode_range, umi_range = self.options.resolved_ranges()
        if barcode_range[1] < barcode_range[0] or umi_range[1] < umi_range[0]:
            raise SingleCellAdapterError(
                "Barcode/UMI ranges are inverted — the end offset must not be "
                "smaller than the start offset."
            )
        warnings.append(
            "Record count is only known after assembly: TRUST4 will run when "
            "the job starts, using the "
            f"{self.options.species} reference with barcode "
            f"{barcode_range[0]}-{barcode_range[1]} and UMI "
            f"{umi_range[0]}-{umi_range[1]} on R1."
        )
        return None, warnings

    def parse(self, files: dict[str, Path]) -> list[UnifiedRecord]:
        r1, r2 = self._require_pair(files)
        barcode_range, umi_range = self.options.resolved_ranges()

        out_dir = (self.work_dir or Path.cwd()) / "trust4"
        trust4_outputs = self.runner.run_fastq(
            r1, r2, out_dir, barcode_range=barcode_range, umi_range=umi_range
        )
        self._stage_done(self.pre_stages[0])

        trust4_adapter = Trust4Adapter()
        records = trust4_adapter.parse(trust4_outputs)
        self.warnings.extend(trust4_adapter.warnings)
        self.parse_report = trust4_adapter.parse_report
        self._adopt_source_annotations(trust4_adapter)
        return records
