"""
Positive and negative tests of pre-execution workflow validation
(Supplementary Note S1): the job-launch validator must accept the three
predefined workflows and refuse each deliberately invalid composition, naming
the step at fault.

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_workflow_validation -v

Inputs are tiny FASTQ/FASTA files written to a temporary directory with
SRA-style headers, i.e. no pRESTO annotations -- the state of a fresh upload.
Companion files are validated by presence only, so their parameters carry a
placeholder id.
"""

import tempfile
import unittest
from pathlib import Path

from app.pipeline.validator import PipelineValidationError, validate_pipeline

READ = "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT"
FILE = "companion-file-id"


def fastq(n: int = 3) -> str:
    return "".join(f"@SRR1.{i} {i} length=40\n{READ}\n+\n{'I' * len(READ)}\n" for i in range(n))


def fasta(n: int = 3) -> str:
    return "".join(f">SRR1.{i}\n{READ}\n" for i in range(n))


# The predefined workflows, as the frontend sends them (src/pipelines/*.ts);
# the same payloads drive the runtime benchmark in temp/bench/benchmark.py.
RACE_325_275 = [
    {"name": "FilterSeq.quality", "lanes": "R1", "params": {"min_qual": 20}},
    {"name": "FilterSeq.quality", "lanes": "R2", "params": {"min_qual": 20}},
    {"name": "MaskPrimers.score", "lanes": "R1",
     "params": {"primer_file": FILE, "start": 0, "mode": "cut"}},
    {"name": "MaskPrimers.score", "lanes": "R2",
     "params": {"primer_file": FILE, "start": 17, "barcode": True, "mode": "cut", "max_error": 0.5}},
    {"name": "PairSeq.default", "lanes": "paired", "params": {"fields_2": ["BARCODE"], "coord_type": "sra"}},
    {"name": "BuildConsensus.default", "lanes": "R1",
     "params": {"barcode_field": "BARCODE", "primer_field": "PRIMER", "primer_freq": 0.6,
                "max_error": 0.1, "max_gap": 0.5}},
    {"name": "BuildConsensus.default", "lanes": "R2",
     "params": {"barcode_field": "BARCODE", "max_error": 0.1, "max_gap": 0.5}},
    {"name": "PairSeq.default", "lanes": "paired", "params": {"coord_type": "presto"}},
    {"name": "AssembleSeq.sequential", "lanes": "paired",
     "params": {"ref_file": FILE, "rc": "tail", "scan_reverse": True, "swap_head_tail": True,
                "head_fields": ["CONSCOUNT"], "tail_fields": ["CONSCOUNT", "PRCONS"],
                "aligner": "blastn"}},
    {"name": "MaskPrimers.align", "lanes": "paired",
     "params": {"primer_file": FILE, "max_len": 100, "max_error": 0.3, "mode": "tag",
                "rev_primer": True, "skip_rc": True, "primer_field": "CREGION"}},
    {"name": "ParseHeaders.collapse", "lanes": "paired",
     "params": {"fields": ["CONSCOUNT"], "actions": ["min"]}},
    {"name": "CollapseSeq.default", "lanes": "paired",
     "params": {"max_missing": 20, "inner": True, "uniq_fields": ["CREGION"],
                "copy_fields": ["CONSCOUNT"], "copy_actions": ["sum"]}},
    {"name": "SplitSeq.group", "lanes": "paired", "params": {"field": "CONSCOUNT", "threshold": 2}},
    {"name": "ParseHeaders.table", "lanes": "paired",
     "params": {"fields": ["ID", "CREGION", "CONSCOUNT", "DUPCOUNT"]}},
]

UMI_2X250 = [
    {"name": "FilterSeq.quality", "lanes": "R1", "params": {"min_qual": 20, "missing_chars": "#"}},
    {"name": "FilterSeq.quality", "lanes": "R2", "params": {"min_qual": 20, "missing_chars": "#"}},
    {"name": "MaskPrimers.score", "lanes": "R1",
     "params": {"primer_file": FILE, "start": 15, "mode": "cut", "barcode": True}},
    {"name": "MaskPrimers.score", "lanes": "R2", "params": {"primer_file": FILE, "start": 0, "mode": "mask"}},
    {"name": "PairSeq.default", "lanes": "paired", "params": {"fields_1": ["BARCODE"], "coord_type": "sra"}},
    {"name": "BuildConsensus.default", "lanes": "R1",
     "params": {"barcode_field": "BARCODE", "primer_field": "PRIMER", "primer_freq": 0.6,
                "max_error": 0.1, "max_gap": 0.5}},
    {"name": "BuildConsensus.default", "lanes": "R2",
     "params": {"barcode_field": "BARCODE", "max_error": 0.1, "max_gap": 0.5}},
    {"name": "PairSeq.default", "lanes": "paired", "params": {"coord_type": "presto"}},
    {"name": "AssembleSeq.align", "lanes": "paired",
     "params": {"swap_head_tail": True, "rc": "tail", "head_fields": ["CONSCOUNT"],
                "tail_fields": ["CONSCOUNT", "PRCONS"]}},
    {"name": "ParseHeaders.collapse", "lanes": "paired", "params": {"fields": ["CONSCOUNT"], "actions": ["min"]}},
    {"name": "CollapseSeq.default", "lanes": "paired",
     "params": {"max_missing": 20, "inner": True, "uniq_fields": ["PRCONS"],
                "copy_fields": ["CONSCOUNT"], "copy_actions": ["sum"]}},
    {"name": "SplitSeq.group", "lanes": "paired", "params": {"field": "CONSCOUNT", "threshold": 2}},
    {"name": "ParseHeaders.table", "lanes": "paired", "params": {"fields": ["ID", "PRCONS", "CONSCOUNT", "DUPCOUNT"]}},
]

NONUMI_2X250 = [
    {"name": "AssembleSeq.align", "lanes": "paired", "params": {"swap_head_tail": True, "rc": "tail"}},
    {"name": "FilterSeq.quality", "lanes": "paired", "params": {"min_qual": 20}},
    {"name": "MaskPrimers.score", "lanes": "paired",
     "params": {"primer_file": FILE, "start": 4, "mode": "mask", "primer_field": "VPRIMER"}},
    {"name": "MaskPrimers.score", "lanes": "paired",
     "params": {"primer_file": FILE, "start": 4, "mode": "cut", "rev_primer": True, "primer_field": "CPRIMER"}},
    {"name": "CollapseSeq.default", "lanes": "paired",
     "params": {"max_missing": 20, "inner": True, "uniq_fields": ["CPRIMER"],
                "copy_fields": ["VPRIMER"], "copy_actions": ["set"]}},
    {"name": "SplitSeq.group", "lanes": "paired", "params": {"field": "DUPCOUNT", "threshold": 2}},
    {"name": "ParseHeaders.table", "lanes": "paired", "params": {"fields": ["ID", "DUPCOUNT", "CPRIMER", "VPRIMER"]}},
]


def without(steps, index):
    return [s for i, s in enumerate(steps) if i != index]


def with_params(step, **params):
    return {**step, "params": {**step["params"], **params}}


class WorkflowValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls.r1 = d / "reads_R1.fastq"
        cls.r2 = d / "reads_R2.fastq"
        cls.fa1 = d / "reads_R1.fasta"
        cls.fa2 = d / "reads_R2.fasta"
        cls.r1.write_text(fastq())
        cls.r2.write_text(fastq())
        cls.fa1.write_text(fasta())
        cls.fa2.write_text(fasta())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @property
    def paired(self):
        return [str(self.r1), str(self.r2)]

    def assertAccepted(self, steps, files):
        ok, _, _ = validate_pipeline(steps, files)
        self.assertTrue(ok)

    def assertRejected(self, steps, files, pattern):
        with self.assertRaisesRegex(PipelineValidationError, pattern):
            validate_pipeline(steps, files)

    # --- positive: the predefined workflows --------------------------------

    def test_accepts_race_325_275(self):
        self.assertAccepted(RACE_325_275, self.paired)

    def test_accepts_umi_2x250(self):
        self.assertAccepted(UMI_2X250, self.paired)

    def test_accepts_nonumi_2x250(self):
        self.assertAccepted(NONUMI_2X250, self.paired)

    # --- negative: missing annotation --------------------------------------

    def test_rejects_consensus_before_any_barcode_exists(self):
        steps = [RACE_325_275[5]]  # BuildConsensus R1 straight on raw reads
        self.assertRejected(steps, self.paired, r"Step 1 \(BuildConsensus.default\)")

    def test_rejects_consensus_when_barcode_was_never_copied_to_mate(self):
        # UMI workflow without the PairSeq that copies BARCODE from R1 to R2:
        # R2 has no barcode when its consensus is built.
        self.assertRejected(without(UMI_2X250, 4), self.paired,
                            r"BuildConsensus.default\) on R2")

    # --- negative: incorrect file type -------------------------------------

    def test_rejects_quality_filter_on_fasta(self):
        steps = [{"name": "FilterSeq.quality", "lanes": "R1", "params": {"min_qual": 20}}]
        self.assertRejected(steps, [str(self.fa1)], r"FilterSeq.quality")

    def test_rejects_mixed_fasta_and_fastq_inputs(self):
        self.assertRejected(NONUMI_2X250, [str(self.r1), str(self.fa2)], "same format")

    # --- negative: absent companion file -----------------------------------

    def test_rejects_primer_masking_without_primer_file(self):
        steps = [with_params(NONUMI_2X250[2], primer_file=None)]
        self.assertRejected(steps, [str(self.r1)], r"Missing required uploads: MaskPrimers.score.primer_file")

    def test_rejects_reference_assembly_without_reference(self):
        steps = [with_params(RACE_325_275[8], ref_file=None)]
        self.assertRejected(steps, self.paired, r"AssembleSeq.sequential.ref_file")

    # --- negative: invalid read-stream state -------------------------------

    def test_rejects_pairing_on_single_file_input(self):
        self.assertRejected([RACE_325_275[4]], [str(self.r1)], "requires two input files")

    def test_rejects_assembly_on_single_file_input(self):
        self.assertRejected([NONUMI_2X250[0]], [str(self.r1)], "requires two input files")

    def test_rejects_r2_step_on_single_file_input(self):
        self.assertRejected([RACE_325_275[1]], [str(self.r1)], "R2")

    # --- negative: impossible operation order ------------------------------

    def test_rejects_per_mate_step_after_mates_were_merged(self):
        steps = [NONUMI_2X250[0], RACE_325_275[1]]  # assemble, then FilterSeq on R2
        self.assertRejected(steps, self.paired, r"Step 2")

    def test_rejects_pairing_after_mates_were_merged(self):
        steps = [NONUMI_2X250[0], RACE_325_275[7]]  # assemble, then PairSeq
        self.assertRejected(steps, self.paired, r"PairSeq.default requires two input files")

    def test_rejects_any_step_after_an_unbounded_split(self):
        # Grouping on a free-text annotation fans out into one file per value.
        split = {"name": "SplitSeq.group", "lanes": "paired", "params": {"field": "VPRIMER"}}
        steps = [NONUMI_2X250[0], NONUMI_2X250[2], split, NONUMI_2X250[4]]
        self.assertRejected(steps, self.paired, r"Step 4")

    def test_rejects_field_that_does_not_exist_at_that_point(self):
        split = {"name": "SplitSeq.group", "lanes": "paired", "params": {"field": "PRIMER"}}
        steps = [NONUMI_2X250[0], NONUMI_2X250[2], split]  # the field is VPRIMER here
        self.assertRejected(steps, self.paired, r"field 'PRIMER' not found")

    def test_rejects_unknown_operation(self):
        steps = [{"name": "FilterSeq.nonexistent", "lanes": "R1", "params": {}}]
        self.assertRejected(steps, [str(self.r1)], "nonexistent")


if __name__ == "__main__":
    unittest.main()
