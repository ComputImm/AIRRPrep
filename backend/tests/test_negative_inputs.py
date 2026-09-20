"""
Negative tests: the inputs AIRRPrep must refuse rather than process.

Each class here covers one of the refusals the manuscript claims
(Supplementary Table S7 and Supplementary Note S1). They are grouped in one
file so that "what does AIRRPrep refuse, and does it really" can be answered
by running a single module.

  * generic FASTA with no way to recover a cell barcode;
  * generic FASTA whose mapping file does not cover every sequence;
  * a BAM whose CB/UB tags cannot be used -- neither route falls back to a
    barcode-free assembly;
  * a TRUST4 file pair that does not belong together;
  * invalid bulk workflow compositions (delegated to
    tests/test_workflow_validation.py, asserted here as a count so the
    manuscript's "3 accepted, 14 refused" cannot drift silently).

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_negative_inputs -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.singlecell.adapters.bam_adapter import BamAdapter
from app.singlecell.adapters.generic_fasta_adapter import GenericFastaAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.errors import SingleCellAdapterError, SingleCellConfigError
from app.singlecell.models import Trust4Options
from app.singlecell.trust4_runner import Trust4Runner

FASTA = (
    ">AAACCTG-1_contig_1\nACGTACGT\n"
    ">AAACCTG-1_contig_2\nGGGGCCCC\n"
    ">TTTGGGA-1_contig_1\nTTTTAAAA\n"
)


class TmpDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path


class GenericFastaRefusals(TmpDirTestCase):
    """Supplementary Table S7, cases G3 and G4."""

    def test_no_barcode_rule_at_all_is_refused(self):
        fasta = self.write("seqs.fasta", FASTA)
        with self.assertRaisesRegex(
            SingleCellAdapterError, "recover the cell barcode"
        ):
            GenericFastaAdapter().parse({"fasta": fasta})

    def test_mapping_that_misses_one_sequence_is_refused(self):
        fasta = self.write("seqs.fasta", FASTA)
        mapping = self.write(
            "map.tsv",
            "sequence_id\tcell_id\tumi_count\tread_count\n"
            "AAACCTG-1_contig_1\tAAACCTG-1\t3\t30\n"
            "AAACCTG-1_contig_2\tAAACCTG-1\t1\t10\n",
        )
        with self.assertRaisesRegex(SingleCellAdapterError, "1 of 3 sequences") as cm:
            GenericFastaAdapter().parse({"fasta": fasta, "barcode_map": mapping})
        # The message must name the sequence that could not be placed.
        self.assertIn("TTTGGGA-1_contig_1", str(cm.exception))

    def test_a_header_rule_that_matches_nothing_is_refused(self):
        fasta = self.write("seqs.fasta", FASTA)
        adapter = GenericFastaAdapter(barcode_header_regex=r"^CELL:(\w+)$")
        with self.assertRaisesRegex(SingleCellAdapterError, "3 of 3 sequences"):
            adapter.parse({"fasta": fasta})

    def test_an_invalid_regex_is_reported_not_ignored(self):
        fasta = self.write("seqs.fasta", FASTA)
        adapter = GenericFastaAdapter(barcode_header_regex=r"^([ACGT")
        with self.assertRaisesRegex(SingleCellAdapterError, "not valid"):
            adapter.parse({"fasta": fasta})


class UnusableBamTagRefusals(TmpDirTestCase):
    """Supplementary Table S7, cases T3n1--T3n3.

    A BAM whose CB/UB tags TRUST4 cannot use must be refused, never assembled
    without barcodes: a barcode-free assembly looks valid but has no cell
    resolution at all.
    """

    def runner(self) -> Trust4Runner:
        with mock.patch.dict(
            "app.singlecell.trust4_runner.TRUST4_SPECIES_REFS",
            {"human": {"ref": "ref.fa", "vdj_ref": "bcrtcr.fa"}},
        ):
            runner = Trust4Runner(species="human", binary="run-trust4")
        runner.require_available = lambda: None
        runner.require_samtools = lambda: None
        return runner

    def test_genome_route_failure_is_not_retried_without_barcodes(self):
        """T3n2: bam-extractor fails; the run stops rather than dropping CB/UB."""
        runner = self.runner()
        calls = []

        def failing_execute(cmd, out_dir):
            calls.append(cmd)
            raise SingleCellConfigError("TRUST4 exited with code 1")

        runner._execute = failing_execute
        with self.assertRaisesRegex(
            SingleCellConfigError, "instead of retrying without barcodes"
        ):
            runner.run_bam(self.write("possorted.bam", ""), self.dir / "out")
        self.assertEqual(len(calls), 1, "TRUST4 must not be invoked a second time")
        self.assertIn("--barcode", calls[0])

    def test_samtools_route_refuses_reads_without_a_cb_tag(self):
        """T3n3: none of the reads carries CB, so no read has a cell."""
        runner = self.runner()
        out = self.dir / "out"

        def fake_piped(collate, to_fastq):
            out.mkdir(parents=True, exist_ok=True)
            # samtools writes the cDNA read as unpaired for a 10x BAM.
            (out / "from_bam_1.fq").write_text("")
            (out / "from_bam_2.fq").write_text("")
            (out / "from_bam_s.fq").write_text("")
            (out / "from_bam_0.fq").write_text(
                "@r1\tUB:Z:TTTT\nACGT\n+\nIIII\n@r2\nACGT\n+\nIIII\n"
            )

        runner._run_piped = fake_piped
        runner._execute = lambda cmd, out_dir: {}
        with self.assertRaisesRegex(SingleCellConfigError, "CB tag"):
            runner.run_bam_via_fastq(self.write("example.bam", ""), out)
        self.assertEqual(runner.tag_stats["reads_with_barcode"], 0)

    def test_contig_aligned_bam_is_refused_before_assembly(self):
        """T3n1: all_contig.bam on the genome-coordinate route."""
        runner = self.runner()
        vdj_ref = self.write("bcrtcr.fa", ">IGHV1-2 chr14 105000 106000 -\nACGT\n")
        runner.vdj_ref_fasta = str(vdj_ref)
        adapter = BamAdapter(options=Trust4Options(), runner=runner)

        bam = self.dir / "all_contig.bam"
        bam.write_bytes(b"")
        with mock.patch(
            "app.singlecell.adapters.bam_adapter.read_bam_reference_names",
            return_value=["AAACCTG-1_contig_1", "AAACCTG-1_contig_2"],
        ):
            with self.assertRaisesRegex(
                SingleCellAdapterError, "not aligned to a reference genome"
            ):
                adapter.parse({"bam": bam})

    def test_bam_with_no_reference_sequences_is_refused(self):
        runner = self.runner()
        vdj_ref = self.write("bcrtcr.fa", ">IGHV1-2 chr14 105000 106000 -\nACGT\n")
        runner.vdj_ref_fasta = str(vdj_ref)
        adapter = BamAdapter(options=Trust4Options(), runner=runner)

        bam = self.dir / "empty.bam"
        bam.write_bytes(b"")
        with mock.patch(
            "app.singlecell.adapters.bam_adapter.read_bam_reference_names",
            return_value=[],
        ):
            with self.assertRaisesRegex(
                SingleCellAdapterError, "declares no reference sequences"
            ):
                adapter.parse({"bam": bam})


class MismatchedTrust4PairRefusals(TmpDirTestCase):
    """A TRUST4 annot.fa and barcode report from two different runs."""

    annot = (
        ">AAACCTG-1_0 x\nACGTACGT\n"
        ">AAACCTG-1_1 x\nGGGGCCCC\n"
        ">TTTGGGA-1_0 x\nTTTTAAAA\n"
    )
    header = (
        "#barcode\tcell_type\tchain1\tchain2"
        "\tsecondary_chain1\tsecondary_chain2\n"
    )

    def test_report_naming_no_contig_of_this_annot_is_refused(self):
        annot = self.write("trust4_annot.fa", self.annot)
        report = self.write(
            "trust4_barcode_report.tsv",
            self.header
            + "AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,other_run_7\t*\t*\t*\n",
        )
        with self.assertRaisesRegex(
            SingleCellAdapterError, "None of the 3 TRUST4 contigs"
        ):
            Trust4Adapter().parse(
                {"annot_fasta": annot, "barcode_report": report}
            )

    def test_annot_without_any_mapping_file_is_refused(self):
        annot = self.write("trust4_annot.fa", self.annot)
        with self.assertRaisesRegex(SingleCellAdapterError, "barcode_report"):
            Trust4Adapter().parse({"annot_fasta": annot})

    def test_a_contig_claimed_by_two_barcodes_stops_the_run(self):
        annot = self.write("trust4_annot.fa", self.annot)
        report = self.write(
            "trust4_barcode_report.tsv",
            self.header
            + "AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,AAACCTG-1_0\t*\t*\t*\n"
            + "TTTGGGA-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,3,AAACCTG-1_0\t*\t*\t*\n",
        )
        with self.assertRaisesRegex(SingleCellAdapterError, "more than one"):
            Trust4Adapter().parse(
                {"annot_fasta": annot, "barcode_report": report}
            )

    def test_airr_table_from_another_run_contributes_nothing(self):
        """Rows naming contigs absent from annot.fa are ignored, not guessed at."""
        annot = self.write("trust4_annot.fa", self.annot)
        airr = self.write(
            "trust4_barcode_airr.tsv",
            "sequence_id\tsequence\tcell_id\n"
            "some_other_run_0\tACGTACGT\tAAACCTG-1\n",
        )
        with self.assertRaisesRegex(
            SingleCellAdapterError, "None of the 3 TRUST4 contigs"
        ):
            Trust4Adapter().parse({"annot_fasta": annot, "airr_tsv": airr})


class WorkflowCompositionRefusalCount(unittest.TestCase):
    """The manuscript's "3 accepted, 14 refused" must stay true."""

    def test_the_validator_suite_still_covers_three_and_fourteen(self):
        from tests import test_workflow_validation as suite

        names = [
            n for n in dir(suite.WorkflowValidationTests) if n.startswith("test_")
        ]
        accepted = [n for n in names if n.startswith("test_accepts_")]
        refused = [n for n in names if n.startswith("test_rejects_")]
        self.assertEqual(len(accepted), 3, "the three predefined workflows")
        self.assertEqual(
            len(refused), 14,
            "Supplementary Note S1 reports 14 invalid compositions; if that "
            "set changes, change the supplement with it",
        )


if __name__ == "__main__":
    unittest.main()
