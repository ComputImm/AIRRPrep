# app/singlecell/trust4_runner.py
"""
Subprocess wrapper around the TRUST4 `run-trust4` driver.

Input modes:

  run_fastq(r1, r2, ...)
      10x paired FASTQ.
      R1 carries cell barcode + UMI.
      R2 carries cDNA.

  run_bam(bam, ...)
      10x genome-aligned BAM, assembled with TRUST4 reading the CB/UB tags.

  run_bam_via_fastq(bam, ...)
      Converts BAM -> FASTQ with samtools while preserving CB/UB tags,
      then gives those tags to TRUST4 through sidecar FASTA files.

Every mode runs TRUST4 in barcode mode, and a run that does not produce a
contig -> cell mapping is a failure. There is deliberately no fallback to
TRUST4's barcode-free BAM mode: that mode completes and writes valid-looking
contigs, but without cell barcodes or UMIs, so it cannot produce single-cell
output and reporting it as a success would hide the loss of cell identity.

Each mode returns the TRUST4 output files keyed by the role names
Trust4Adapter.parse() takes:

    annot_fasta     trust4_annot.fa            (required)
    barcode_report  trust4_barcode_report.tsv  (when TRUST4 wrote it)
    airr_tsv        trust4_barcode_airr.tsv    (per-cell AIRR table; trust4_airr.tsv as fallback)

At least one of barcode_report / airr_tsv must be present, since those are
where the cell barcode of each contig comes from.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.config import (
    SAMTOOLS_BIN,
    TRUST4_BARCODE_WHITELIST,
    TRUST4_BIN,
    TRUST4_DEFAULT_SPECIES,
    TRUST4_SPECIES_REFS,
    TRUST4_THREADS,
    TRUST4_TIMEOUT,
)
from app.singlecell.errors import SingleCellConfigError

logger = logging.getLogger("celery_worker")

# Prefix passed to run-trust4 -o.
_OUT_PREFIX = "trust4"

# BAM tags used by Cell Ranger / 10x.
_BAM_BARCODE_TAG = "CB"
_BAM_UMI_TAG = "UB"


class Trust4Runner:
    def __init__(
        self,
        species: str = TRUST4_DEFAULT_SPECIES,
        binary: str = TRUST4_BIN,
        threads: int = TRUST4_THREADS,
        barcode_whitelist: str | None = TRUST4_BARCODE_WHITELIST,
        samtools: str = SAMTOOLS_BIN,
    ):
        self.samtools = samtools

        if species not in TRUST4_SPECIES_REFS:
            raise SingleCellConfigError(
                f"Unknown TRUST4 species {species!r}. "
                f"Supported: {', '.join(sorted(TRUST4_SPECIES_REFS))}."
            )

        refs = TRUST4_SPECIES_REFS[species]

        self.species = species
        self.binary = binary
        self.threads = max(1, threads)
        self.barcode_whitelist = barcode_whitelist

        self.ref_fasta = refs["ref"]
        self.vdj_ref_fasta = refs["vdj_ref"]

        #: Counts from the last BAM -> FASTQ extraction (reads seen, reads
        #: carrying CB, reads carrying UB), so a run can report how much of
        #: the input kept its cell identity.
        self.tag_stats: dict[str, int] = {}

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------

    def check_binary(self) -> list[str]:
        """Problems with the TRUST4 installation."""
        if shutil.which(self.binary) or Path(self.binary).is_file():
            return []
        return [
            f"TRUST4 driver not found (TRUST4_BIN={self.binary!r}). "
            "Set TRUST4_BIN to the run-trust4 script."
        ]

    def check_samtools(self) -> list[str]:
        """Problems with samtools used by the BAM->FASTQ path."""
        if shutil.which(self.samtools) or Path(self.samtools).is_file():
            return []
        return [
            f"samtools not found (SAMTOOLS_BIN={self.samtools!r}). It is "
            "required only for the 'extract reads first' BAM option."
        ]

    def require_samtools(self) -> None:
        problems = self.check_samtools()
        if problems:
            raise SingleCellConfigError("; ".join(problems))

    def check_references(self) -> list[str]:
        """Problems with this runner's species reference files."""
        problems = []
        if not Path(self.vdj_ref_fasta).is_file():
            problems.append(
                f"TRUST4 V(D)J coordinate reference missing for {self.species} "
                f"({self.vdj_ref_fasta}). Set TRUST4_REF_DIR or the per-species "
                "override env var."
            )
        if not Path(self.ref_fasta).is_file():
            problems.append(
                f"TRUST4 IMGT reference missing for {self.species} "
                f"({self.ref_fasta}). Set TRUST4_REF_DIR or the per-species "
                "override env var."
            )
        if self.barcode_whitelist and not Path(self.barcode_whitelist).is_file():
            problems.append(
                "TRUST4_BARCODE_WHITELIST is set but the file does not exist "
                f"({self.barcode_whitelist})."
            )
        return problems

    def check_available(self) -> list[str]:
        """Return human-readable problems; empty means ready to run."""
        return [*self.check_binary(), *self.check_references()]

    def require_available(self) -> None:
        problems = self.check_available()
        if problems:
            raise SingleCellConfigError(
                "TRUST4 is required to process this input but is not usable "
                "on this server: "
                + "; ".join(problems)
                + ". Alternatively, run TRUST4 externally in barcode mode and "
                "upload the result (*_annot.fa + *_barcode_report.tsv)."
            )

    # ------------------------------------------------------------------
    # FASTQ
    # ------------------------------------------------------------------

    def run_fastq(
        self,
        r1_fastq: Path,
        r2_fastq: Path,
        out_dir: Path,
        barcode_range: tuple[int, int] = (0, 15),
        umi_range: tuple[int, int] = (16, 25),
    ) -> dict[str, Path]:
        """Assemble from a 10x paired FASTQ set (R1 = barcode + UMI, R2 = cDNA).

        The barcode and UMI slices of R1 are given with ``--readFormat``
        (inclusive 0-based ranges, the same convention as the chemistry
        presets). The older ``--barcodeRange``/``--umiRange`` options are no
        longer documented by TRUST4, and with TRUST4 1.1.9 they extract an
        empty barcode for every read: the run completes, but every contig
        lands in one nameless "cell" and no output can be produced.
        """
        r1_abs = str(r1_fastq.resolve())
        r2_abs = str(r2_fastq.resolve())

        cmd = [
            *self._base_cmd(out_dir),
            "-u", r2_abs,
            "--barcode", r1_abs,
            "--UMI", r1_abs,
            "--readFormat",
            f"bc:{barcode_range[0]}:{barcode_range[1]},um:{umi_range[0]}:{umi_range[1]}",
        ]
        if self.barcode_whitelist:
            cmd += ["--barcodeWhitelist", self.barcode_whitelist]

        return self._execute(cmd, out_dir)

    # ------------------------------------------------------------------
    # BAM
    # ------------------------------------------------------------------

    def run_bam(self, bam: Path, out_dir: Path) -> dict[str, Path]:
        """
        Assemble directly from a genome-aligned BAM, reading the cell barcode
        and UMI from its CB/UB tags.

        If TRUST4 cannot use the tags the run fails. It is not retried in
        TRUST4's barcode-free BAM mode, because that mode discards the cell
        barcodes and UMIs the single-cell output is built from.
        """
        self.require_available()
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            *self._base_cmd(out_dir),
            "-b", str(bam.resolve()),
            "--barcode", _BAM_BARCODE_TAG,
            "--UMI", _BAM_UMI_TAG,
            "--abnormalUnmapFlag",
        ]
        if self.barcode_whitelist:
            cmd += ["--barcodeWhitelist", self.barcode_whitelist]

        try:
            return self._execute(cmd, out_dir)
        except SingleCellConfigError as exc:
            raise SingleCellConfigError(
                f"TRUST4 could not assemble this BAM using its {_BAM_BARCODE_TAG}/"
                f"{_BAM_UMI_TAG} tags: {self._short_error(exc)}. The run was "
                "stopped instead of retrying without barcodes, because a "
                "barcode-free assembly cannot be assigned to cells. If the BAM "
                "does carry CB/UB tags, try the \"Extract reads with samtools "
                "first\" option, which copies the tags into TRUST4's FASTQ path."
            ) from exc

    # ------------------------------------------------------------------
    # BAM -> FASTQ
    # ------------------------------------------------------------------

    def run_bam_via_fastq(self, bam: Path, out_dir: Path) -> dict[str, Path]:
        """
        Assemble from BAM by converting it to FASTQ first.

        Useful for BAMs that TRUST4's bam-extractor cannot interpret, for
        example BAMs aligned to assembled V(D)J contigs. CB/UB are copied from
        the BAM tags into TRUST4 barcode/UMI sidecar FASTA files; reads with
        no CB tag cannot be assigned to a cell and are counted, then dropped.

        10x BAMs normally hold only the cDNA read (flagged READ2, mate
        absent), so the reads samtools writes as unpaired or singleton are
        kept and assembled as single-end input. Only when the BAM really
        contains both mates is TRUST4 given paired input.
        """
        self.require_available()
        self.require_samtools()
        out_dir.mkdir(parents=True, exist_ok=True)

        r1 = out_dir / "from_bam_1.fq"
        r2 = out_dir / "from_bam_2.fq"
        unpaired = out_dir / "from_bam_0.fq"
        singletons = out_dir / "from_bam_s.fq"

        collate = [
            self.samtools, "collate", "-u", "-O", "-@", str(self.threads),
            str(bam.resolve()),
        ]
        to_fastq = [
            self.samtools, "fastq",
            "-T", f"{_BAM_BARCODE_TAG},{_BAM_UMI_TAG}",
            "-1", str(r1), "-2", str(r2),
            "-0", str(unpaired), "-s", str(singletons),
            "-n", "-",
        ]

        logger.info("Converting BAM to FASTQ: %s | %s", " ".join(collate), " ".join(to_fastq))
        self._run_piped(collate, to_fastq)

        def has_reads(path: Path) -> bool:
            return path.is_file() and path.stat().st_size > 0

        if has_reads(r1):
            paired = True
            reads = [r1, r2]
        else:
            paired = False
            single = out_dir / "from_bam_single.fq"
            with single.open("wb") as out:
                for part in (unpaired, singletons):
                    if has_reads(part):
                        with part.open("rb") as src:
                            shutil.copyfileobj(src, out)
            if not has_reads(single):
                raise SingleCellConfigError(
                    "Converting the BAM to FASTQ produced no reads."
                )
            reads = [single]

        barcodes, umis, stats = self._split_tag_sidecars(reads, out_dir)
        stats["paired"] = int(paired)
        self.tag_stats = stats

        if stats["reads_with_barcode"] == 0:
            raise SingleCellConfigError(
                f"None of the {stats['reads']} reads carried a "
                f"{_BAM_BARCODE_TAG} tag, so no read could be assigned "
                "to a cell. This BAM does not look like 10x output."
            )

        logger.info("BAM->FASTQ tag counts: %s", stats)

        read_args = ["-1", str(r1), "-2", str(r2)] if paired else ["-u", str(reads[0])]
        cmd = [
            *self._base_cmd(out_dir),
            *read_args,
            "--barcode", str(barcodes),
            "--UMI", str(umis),
        ]
        if self.barcode_whitelist:
            cmd += ["--barcodeWhitelist", self.barcode_whitelist]

        return self._execute(cmd, out_dir)

    # ------------------------------------------------------------------
    # BAM tag extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _split_tag_sidecars(
        reads: list[Path], out_dir: Path
    ) -> tuple[Path, Path, dict[str, int]]:
        """
        Move CB/UB tags from FASTQ comments into TRUST4 sidecar FASTA files.

        ``reads`` is [single-end file] or [R1, R2]; the files are rewritten in
        place to keep only reads that carry a cell barcode, in step with the
        sidecars.

        Example samtools FASTQ header:

            @READ CB:Z:AAACCTGAGAAACCAT-1 UB:Z:TTTTGGGG

        TRUST4 sidecars:

            >READ
            AAACCTGAGAAACCAT-1

        and:

            >READ
            TTTTGGGG
        """
        barcodes = out_dir / "from_bam_barcode.fa"
        umis = out_dir / "from_bam_umi.fa"
        stats = {"reads": 0, "reads_with_barcode": 0, "reads_with_umi": 0}

        cleaned = [out_dir / f"_reads{i}.tmp" for i in range(len(reads))]
        inputs = [path.open() for path in reads]
        outputs = [path.open("w") for path in cleaned]

        with barcodes.open("w") as bc, umis.open("w") as um:
            while True:
                records = [[fh.readline() for _ in range(4)] for fh in inputs]
                if not records[0][0]:
                    break
                stats["reads"] += 1

                header = records[0][0].rstrip("\n")
                name = header[1:].split()[0] if len(header) > 1 else ""

                tags = {}
                for part in header.split()[1:]:
                    if part.count(":") >= 2:
                        key, _, value = part.partition(":")
                        _, _, value = value.partition(":")
                        tags[key] = value

                barcode = tags.get(_BAM_BARCODE_TAG)
                if not barcode or barcode == "-":
                    continue
                stats["reads_with_barcode"] += 1
                umi = tags.get(_BAM_UMI_TAG)
                if umi and umi != "-":
                    stats["reads_with_umi"] += 1

                for record, out in zip(records, outputs):
                    if record[0]:
                        out.write(f"@{name}\n{record[1]}{record[2]}{record[3]}")
                bc.write(f">{name}\n{barcode}\n")
                # A missing UMI is survivable; keep the sidecars aligned.
                um.write(f">{name}\n{umi or 'N'}\n")

        for fh in (*inputs, *outputs):
            fh.close()
        for tmp, path in zip(cleaned, reads):
            tmp.replace(path)
        return barcodes, umis, stats

    # ------------------------------------------------------------------
    # subprocess helpers
    # ------------------------------------------------------------------

    def _run_piped(self, first: list[str], second: list[str]) -> None:
        """Run `first | second` and raise useful errors."""
        try:
            p1 = subprocess.Popen(first, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p2 = subprocess.Popen(
                second, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if p1.stdout:
                p1.stdout.close()
            _, err2 = p2.communicate(timeout=TRUST4_TIMEOUT or None)
            p1.wait(timeout=60)
            err1 = p1.stderr.read() if p1.stderr else b""
        except FileNotFoundError as e:
            raise SingleCellConfigError(f"samtools could not be executed: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise SingleCellConfigError(
                f"Converting the BAM to FASTQ timed out after {TRUST4_TIMEOUT}s."
            ) from e

        if p2.returncode != 0 or p1.returncode != 0:
            detail = (err2 or err1 or b"").decode("utf-8", "replace")[-1500:]
            raise SingleCellConfigError(
                "samtools failed while converting the BAM to FASTQ "
                f"(collate={p1.returncode}, fastq={p2.returncode}): {detail}"
            )

    # ------------------------------------------------------------------
    # TRUST4 internals
    # ------------------------------------------------------------------

    def _base_cmd(self, out_dir: Path) -> list[str]:
        self.require_available()
        out_dir.mkdir(parents=True, exist_ok=True)
        return [
            self.binary,
            "-f", str(Path(self.vdj_ref_fasta).resolve()),
            "--ref", str(Path(self.ref_fasta).resolve()),
            "-t", str(self.threads),
            "--od", str(out_dir.resolve()),
            "-o", _OUT_PREFIX,
        ]

    def _execute(self, cmd: list[str], out_dir: Path) -> dict[str, Path]:
        """Run TRUST4 and return its output files keyed by adapter role."""
        logger.info("Running TRUST4: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=TRUST4_TIMEOUT or None
            )
        except FileNotFoundError as e:
            raise SingleCellConfigError(
                f"TRUST4 driver could not be executed ({self.binary}): {e}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise SingleCellConfigError(
                f"TRUST4 timed out after {TRUST4_TIMEOUT}s. Increase "
                "TRUST4_TIMEOUT, or assemble externally and upload the result."
            ) from e

        if result.returncode != 0:
            logger.error("TRUST4 failed (%s): %s", result.returncode, result.stderr)
            raise SingleCellConfigError(
                f"TRUST4 exited with code {result.returncode}: "
                f"{(result.stderr or result.stdout or '')[-2000:]}"
            )

        def non_empty(name: str) -> Path | None:
            path = out_dir / f"{_OUT_PREFIX}_{name}"
            return path if path.is_file() and path.stat().st_size > 0 else None

        outputs = {
            "annot_fasta": non_empty("annot.fa"),
            "barcode_report": non_empty("barcode_report.tsv"),
            # In barcode mode TRUST4 writes the per-cell AIRR table (with
            # cell_id) as *_barcode_airr.tsv; *_airr.tsv has no cell ids there.
            "airr_tsv": non_empty("barcode_airr.tsv") or non_empty("airr.tsv"),
        }
        if outputs["annot_fasta"] is None:
            raise SingleCellConfigError(
                "TRUST4 completed but produced no assembled contigs "
                f"({_OUT_PREFIX}_annot.fa is missing or empty)."
            )
        if outputs["barcode_report"] is None and outputs["airr_tsv"] is None:
            raise SingleCellConfigError(
                "TRUST4 completed but wrote neither a barcode report nor an "
                "AIRR table, so no contig can be assigned to a cell."
            )
        return {role: path for role, path in outputs.items() if path is not None}

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """Keep embedded error messages reasonably short."""
        text = str(exc).strip()
        return text[-1000:] if len(text) > 1000 else text
