"""
Behavioural tests for the single-cell adapters and the provenance/security
changes that accompany them.

    cd presto-backend
    venv/Scripts/python.exe -m unittest discover -s tests -v

Stdlib unittest only, so nothing beyond requirements.txt is needed. No test
touches Redis or runs TRUST4: files are small synthetic fixtures written to a
temporary directory, and external processes are replaced with stubs. They pin
*behaviour* (what is refused, what is never invented); agreement with real
TRUST4 output still has to be checked on real files -- see
test-data/README.md.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.singlecell.adapters.cellranger_adapter import CellRangerAdapter
from app.singlecell.adapters.generic_fasta_adapter import GenericFastaAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.errors import SingleCellAdapterError, SingleCellConfigError
from app.singlecell.trust4_runner import Trust4Runner

FASTA = ">AAACCTG-1_contig_1\nACGTACGT\n>AAACCTG-1_contig_2\nGGGGCCCC\n>TTTGGGA-1_contig_1\nTTTTAAAA\n"


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


class GenericFastaTests(TmpDirTestCase):
    def test_rejects_fasta_without_any_barcode_rule(self):
        """Supplementary Table S7, T5: barcode-free FASTA is refused."""
        fasta = self.write("seqs.fasta", FASTA)
        with self.assertRaisesRegex(SingleCellAdapterError, "recover the cell barcode"):
            GenericFastaAdapter().parse({"fasta": fasta})

    def test_rejects_partial_mapping_instead_of_inventing_cells(self):
        fasta = self.write("seqs.fasta", FASTA)
        mapping = self.write(
            "map.tsv",
            "sequence_id\tcell_id\tumi_count\tread_count\n"
            "AAACCTG-1_contig_1\tAAACCTG-1\t3\t30\n",
        )
        with self.assertRaisesRegex(SingleCellAdapterError, "2 of 3 sequences"):
            GenericFastaAdapter().parse({"fasta": fasta, "barcode_map": mapping})

    def test_header_regex_recovers_real_barcodes(self):
        fasta = self.write("seqs.fasta", FASTA)
        adapter = GenericFastaAdapter(barcode_header_regex=r"^([ACGT]+-\d+)_contig")
        records = adapter.parse({"fasta": fasta})
        self.assertEqual({r.cell_id for r in records}, {"AAACCTG-1", "TTTGGGA-1"})
        self.assertTrue(all(r.is_cell is None and r.high_confidence is None for r in records))
        self.assertEqual(adapter.parse_report["records_without_barcode"], 0)


class Trust4AdapterTests(TmpDirTestCase):
    annot = (
        ">AAACCTG-1_0 x\nACGTACGT\n"
        ">AAACCTG-1_1 x\nGGGGCCCC\n"
        ">TTTGGGA-1_0 x\nTTTTAAAA\n"
    )

    def report(self, rows: list[str]) -> Path:
        header = "#barcode\tcell_type\tchain1\tchain2\tsecondary_chain1\tsecondary_chain2\n"
        return self.write("trust4_barcode_report.tsv", header + "".join(rows))

    def test_current_chain_layout_maps_contigs_by_id_not_position(self):
        # TRUST4 >= 1.0: V,D,J,C,cdr3_nt,cdr3_aa,read_cnt,consensus_id,similarity,full_length
        annot = self.write("trust4_annot.fa", self.annot)
        report = self.report([
            "AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,AAACCTG-1_0,1.00,1"
            "\tTRAV1,*,TRAJ1,TRAC,TGC,C,7,AAACCTG-1_1,0.98,0\t*\t*\n",
        ])
        adapter = Trust4Adapter()
        records = adapter.parse({"annot_fasta": annot, "barcode_report": report})

        by_id = {r.sequence_id: r for r in records}
        self.assertEqual(set(by_id), {"AAACCTG-1_0", "AAACCTG-1_1"})
        self.assertEqual(by_id["AAACCTG-1_0"].cell_id, "AAACCTG-1")
        self.assertEqual(by_id["AAACCTG-1_0"].read_count, 12)
        self.assertEqual(by_id["AAACCTG-1_1"].read_count, 7)

    def test_contig_without_barcode_is_left_out_never_its_own_cell(self):
        annot = self.write("trust4_annot.fa", self.annot)
        report = self.report([
            "AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,AAACCTG-1_0\t*\t*\t*\n",
        ])
        adapter = Trust4Adapter()
        records = adapter.parse({"annot_fasta": annot, "barcode_report": report})

        self.assertNotIn("TTTGGGA-1_0", {r.cell_id for r in records})
        self.assertEqual([r.sequence_id for r in records], ["AAACCTG-1_0"])
        self.assertEqual(adapter.parse_report["contigs_not_in_cell_report"], 2)
        self.assertTrue(any("left out" in w for w in adapter.warnings))

    def test_run_with_no_recoverable_barcode_fails(self):
        annot = self.write("trust4_annot.fa", self.annot)
        # A report whose chain fields name no contig in annot.fa -- e.g. an
        # unrecognised layout, or a report from a different run.
        report = self.report(["AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,other_7\t*\t*\t*\n"])
        with self.assertRaisesRegex(SingleCellAdapterError, "None of the 3 TRUST4 contigs"):
            Trust4Adapter().parse({"annot_fasta": annot, "barcode_report": report})

    def test_contig_claimed_by_two_cells_fails(self):
        annot = self.write("trust4_annot.fa", self.annot)
        report = self.report([
            "AAACCTG-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,12,AAACCTG-1_0\t*\t*\t*\n",
            "TTTGGGA-1\tabT\tTRBV1,*,TRBJ1,TRBC1,TGT,C,3,AAACCTG-1_0\t*\t*\t*\n",
        ])
        with self.assertRaisesRegex(SingleCellAdapterError, "more than one"):
            Trust4Adapter().parse({"annot_fasta": annot, "barcode_report": report})

    def test_airr_table_cell_id_is_a_second_source(self):
        annot = self.write("trust4_annot.fa", self.annot)
        airr = self.write(
            "trust4_airr.tsv",
            "sequence_id\tsequence\tcell_id\n"
            "AAACCTG-1_0\tACGTACGT\tAAACCTG-1\n"
            "TTTGGGA-1_0\tTTTTAAAA\tTTTGGGA-1\n"
            "AAACCTG-1_1\tGGGGCCCC\t\n",
        )
        adapter = Trust4Adapter()
        records = adapter.parse({"annot_fasta": annot, "airr_tsv": airr})
        self.assertEqual(
            {(r.sequence_id, r.cell_id) for r in records},
            {("AAACCTG-1_0", "AAACCTG-1"), ("TTTGGGA-1_0", "TTTGGGA-1")},
        )
        self.assertEqual(adapter.parse_report["contigs_not_in_cell_report"], 1)

    def test_requires_a_mapping_file(self):
        annot = self.write("trust4_annot.fa", self.annot)
        with self.assertRaisesRegex(SingleCellAdapterError, "barcode_report"):
            Trust4Adapter().parse({"annot_fasta": annot})


class CellRangerTests(TmpDirTestCase):
    def test_row_without_barcode_is_not_given_the_contig_id(self):
        fasta = self.write("filtered_contig.fasta", FASTA)
        csv = self.write(
            "filtered_contig_annotations.csv",
            "barcode,is_cell,contig_id,high_confidence,reads,umis,productive\n"
            "AAACCTG-1,true,AAACCTG-1_contig_1,true,30,3,true\n"
            ",true,AAACCTG-1_contig_2,true,10,1,true\n",
        )
        adapter = CellRangerAdapter("filtered_contig")
        records = adapter.parse({"contig_fasta": fasta, "contig_annotations": csv})
        self.assertEqual([r.sequence_id for r in records], ["AAACCTG-1_contig_1"])
        self.assertEqual(adapter.parse_report["rows_without_barcode"], 1)
        self.assertEqual(adapter.parse_report["fasta_records_without_annotation"], 1)

    def test_absent_flags_stay_empty(self):
        tsv = self.write(
            "airr_rearrangement.tsv",
            "cell_id\tsequence_id\tsequence\tconsensus_count\tduplicate_count\tis_cell\n"
            "AAACCTG-1\tAAACCTG-1_contig_1\tACGT\t300\t5\tT\n",
        )
        (record,) = CellRangerAdapter("airr_tsv").parse({"airr_tsv": tsv})
        self.assertEqual((record.umi_count, record.read_count), (5, 300))
        self.assertIs(record.is_cell, True)
        self.assertIsNone(record.high_confidence)


class Trust4RunnerTests(TmpDirTestCase):
    def runner(self) -> Trust4Runner:
        with mock.patch.dict(
            "app.singlecell.trust4_runner.TRUST4_SPECIES_REFS",
            {"human": {"ref": "ref.fa", "vdj_ref": "bcrtcr.fa"}},
        ):
            runner = Trust4Runner(species="human", binary="run-trust4")
        runner.require_available = lambda: None
        return runner

    def test_bam_barcode_failure_is_not_retried_without_barcodes(self):
        runner = self.runner()
        bam = self.write("possorted.bam", "")
        calls = []

        def failing_execute(cmd, out_dir):
            calls.append(cmd)
            raise SingleCellConfigError("TRUST4 exited with code 1")

        runner._execute = failing_execute
        with self.assertRaisesRegex(SingleCellConfigError, "instead of retrying without barcodes"):
            runner.run_bam(bam, self.dir / "out")
        self.assertEqual(len(calls), 1)
        self.assertIn("--barcode", calls[0])

    def test_fastq_barcode_and_umi_are_passed_with_read_format(self):
        # TRUST4 1.1.9 extracts empty barcodes from the deprecated
        # --barcodeRange/--umiRange options (found on real 10x data).
        runner = self.runner()
        runner._execute = lambda cmd, out_dir: cmd
        cmd = runner.run_fastq(self.write("R1.fq", ""), self.write("R2.fq", ""), self.dir / "out",
                               barcode_range=(0, 15), umi_range=(16, 27))
        self.assertIn("--readFormat", cmd)
        self.assertEqual(cmd[cmd.index("--readFormat") + 1], "bc:0:15,um:16:27")
        self.assertNotIn("--barcodeRange", cmd)
        self.assertNotIn("--umiRange", cmd)

    def test_single_end_bam_reads_keep_their_cell_barcodes(self):
        # 10x BAMs hold only the cDNA read, which samtools writes as unpaired.
        reads = self.write(
            "from_bam_single.fq",
            "@r1\tCB:Z:AAACCTGAGAAACCAT-1\tUB:Z:TTTTGGGG\nACGT\n+\nIIII\n"
            "@r2\tUB:Z:CCCC\nACGT\n+\nIIII\n"
            "@r3\tCB:Z:TTTGGGAGAAACCATA-1\nGGGG\n+\nIIII\n",
        )
        barcodes, umis, stats = Trust4Runner._split_tag_sidecars([reads], self.dir)
        self.assertEqual(stats, {"reads": 3, "reads_with_barcode": 2, "reads_with_umi": 1})
        self.assertEqual(reads.read_text().count("@"), 2)
        self.assertEqual(barcodes.read_text(), ">r1\nAAACCTGAGAAACCAT-1\n>r3\nTTTGGGAGAAACCATA-1\n")
        self.assertEqual(umis.read_text(), ">r1\nTTTTGGGG\n>r3\nN\n")

    def test_execute_requires_contigs_and_a_cell_mapping(self):
        runner = self.runner()
        out = self.dir / "out"
        out.mkdir()
        ok = mock.Mock(returncode=0, stdout="", stderr="")

        (out / "trust4_annot.fa").write_text(">c\nACGT\n")
        with mock.patch("subprocess.run", return_value=ok):
            with self.assertRaisesRegex(SingleCellConfigError, "no contig can be assigned"):
                runner._execute(["run-trust4"], out)

        (out / "trust4_barcode_report.tsv").write_text("#barcode\n")
        with mock.patch("subprocess.run", return_value=ok):
            outputs = runner._execute(["run-trust4"], out)
        self.assertEqual(set(outputs), {"annot_fasta", "barcode_report"})


class EmailHashTests(unittest.TestCase):
    def test_email_lookup_value_is_keyed(self):
        from app.core import email_verification as ev

        plain = hashlib.sha256(b"someone@example.org").hexdigest()
        with mock.patch.object(ev, "EMAIL_HASH_SECRET", "key-one"):
            one = ev.hash_email(" Someone@Example.org ")
        with mock.patch.object(ev, "EMAIL_HASH_SECRET", "key-two"):
            two = ev.hash_email("someone@example.org")
        self.assertNotEqual(one, plain)
        self.assertNotEqual(one, two)


class WorkflowProvenanceTests(TmpDirTestCase):
    def test_saved_workflow_records_identity_of_owned_companion_files(self):
        from app.core import pipeline_store as ps

        primer = self.write("AbSeq_R1_primers.fasta", ">p1\nACGT\n")
        stored = mock.Mock(path=str(primer), original_name="AbSeq_R1_primers.fasta")
        steps = [
            {"name": "MaskPrimers.score", "params": {"primer_file": "file-1", "start": 0}},
            {"name": "MaskPrimers.score", "params": {"primer_file": "someone-elses"}},
        ]
        with mock.patch.object(ps, "get_file", return_value=stored):
            cleaned, required = ps.strip_upload_params(steps, owned_file_ids={"file-1"})

        self.assertNotIn("primer_file", cleaned[0]["params"])
        self.assertEqual(
            required[0]["used_file"],
            {
                "name": "AbSeq_R1_primers.fasta",
                "size_bytes": primer.stat().st_size,
                "sha256": hashlib.sha256(primer.read_bytes()).hexdigest(),
            },
        )
        # An id the session does not own is never fingerprinted.
        self.assertNotIn("used_file", required[1])

    def test_import_keeps_only_well_formed_file_identities(self):
        from app.core.pipeline_store import known_files_from_document

        good = {"name": "p.fasta", "size_bytes": 10, "sha256": "a" * 64}
        document = {
            "requires_uploads": [
                {"step_index": 0, "param": "primer_file", "used_file": good},
                {"step_index": 1, "param": "primer_file",
                 "used_file": {"name": "x", "size_bytes": 1, "sha256": "not-a-digest"}},
            ]
        }
        self.assertEqual(known_files_from_document(document), {(0, "primer_file"): good})


if __name__ == "__main__":
    unittest.main()
