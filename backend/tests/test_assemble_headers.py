"""
Header construction in the read-pair assembly wrappers.

AssemblePairs.py names the stitched record after the pair's *coordinate*, not
after the head read's header: with the presto coordinate type that header still
carries the upstream annotations, so using it verbatim writes every head field
twice -- once inside the identifier and once in the merged annotation.

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_assemble_headers -v

The expected headers below are what AssemblePairs.py itself writes for the same
inputs; work/cases/AssemblePairs_{align,join} in the component matrix compares
the two implementations on real reads and is the wider check.
"""

import tempfile
import unittest
from pathlib import Path

from app.presto_wrappers.assemble_pair import run_assemble_align, run_assemble_join

# A 60 nt head and a tail whose reverse complement overlaps its last 30 nt, so
# align finds a single unambiguous overlap and join is a plain concatenation.
HEAD_SEQ = "AGGTCAGCTGGTGGAGTCTGGGGGAGGCTTGGTACAGCCTGGGGGGTCCCTGAGACTCTCC"
TAIL_SEQ = "GGAGAGTCTCAGGGACCCCCCAGGCTGTACCAAGCCTCCCCCAGACTCCACCAGCTGACCT"


def fastq(header: str, seq: str) -> str:
    return f"@{header}\n{seq}\n+\n{'I' * len(seq)}\n"


def header_of(path: str) -> str:
    with open(path) as fh:
        return fh.readline().rstrip("\n")[1:]


class AssembleHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_pair(self, head_header: str, tail_header: str):
        head = self.dir / "head.fastq"
        tail = self.dir / "tail.fastq"
        head.write_text(fastq(head_header, HEAD_SEQ))
        tail.write_text(fastq(tail_header, TAIL_SEQ))
        return str(head), str(tail)

    def test_join_keeps_one_field_per_annotation(self):
        head, tail = self.write_pair(
            "READ1|CONSCOUNT=2|PRCONS=IGHA", "READ1|CONSCOUNT=3"
        )
        result = run_assemble_join(
            head, tail, str(self.dir / "out.fastq"), rc="tail", gap=0,
            head_fields=["CONSCOUNT", "PRCONS"], tail_fields=["CONSCOUNT"],
        )
        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(header_of(result["pass"]), "READ1|CONSCOUNT=2,3|PRCONS=IGHA")

    def test_align_keeps_one_field_per_annotation(self):
        head, tail = self.write_pair(
            "READ1|CONSCOUNT=2|PRCONS=IGHA", "READ1|CONSCOUNT=3"
        )
        result = run_assemble_align(
            head, tail, str(self.dir / "out.fastq"), rc="tail",
            head_fields=["CONSCOUNT", "PRCONS"], tail_fields=["CONSCOUNT"],
            min_len=20,
        )
        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(header_of(result["pass"]), "READ1|CONSCOUNT=2,3|PRCONS=IGHA")

    def test_unannotated_reads_keep_their_identifier(self):
        head, tail = self.write_pair("READ1", "READ1")
        result = run_assemble_join(
            head, tail, str(self.dir / "out.fastq"), rc="tail", gap=0,
        )
        self.assertEqual(header_of(result["pass"]), "READ1")

    def test_raw_sra_mates_assemble_under_their_run_identifier(self):
        # What a fresh upload of an SRA/ENA run looks like: the two mates share
        # an identifier but not a description, so their presto coordinate keys
        # differ. AssemblePairs.py is told --coord sra for such files; AIRRPrep
        # is told nothing and has to recognise the pair anyway.
        head, tail = self.write_pair(
            "ERR346600.1 1 length=250", "ERR346600.1 1 length=251"
        )
        result = run_assemble_join(
            head, tail, str(self.dir / "out.fastq"), rc="tail", gap=0,
        )
        self.assertEqual(result["pass_count"], 1)
        self.assertEqual(header_of(result["pass"]), "ERR346600.1")

    def test_mate_suffixes_are_not_part_of_the_identifier(self):
        head, tail = self.write_pair("READ1/1", "READ1/2")
        result = run_assemble_join(
            head, tail, str(self.dir / "out.fastq"), rc="tail", gap=0,
        )
        self.assertEqual(header_of(result["pass"]), "READ1")

    def test_files_out_of_sync_are_refused(self):
        head, tail = self.write_pair("READ1", "READ2")
        with self.assertRaises(ValueError) as caught:
            run_assemble_join(
                head, tail, str(self.dir / "out.fastq"), rc="tail", gap=0,
            )
        self.assertIn("do not match", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
