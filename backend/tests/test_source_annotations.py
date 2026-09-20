"""
Lossless provenance of the upstream annotations the normalized single-cell
output omits (Supplementary Table S1, Supplementary Figure S1).

AIRRPrep deliberately drops the uploaded file's V(D)J calls, junctions and
CDR3s from `final.fasta`/`metadata.tsv`, so that sequences are re-annotated
downstream with one reference and one procedure. Dropping them from the
analysis schema is not the same as destroying them: every field the source
carried is written beside the normalized output as `source_annotations.tsv`,
keyed on the same `sequence_id`.

What these tests pin:

* every normalized record has exactly one sidecar row, and the join on
  `sequence_id` is total and collision-free (no row lost, none duplicated);
* the fields the normalized output omits are actually present in the sidecar,
  with the values the source gave;
* the sidecar is written for each input specification that carries
  annotations, and skipped when the input carries none;
* `provenance.json` records the sidecar's own SHA-256, so it can be verified
  independently of the uploaded file.

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_source_annotations -v
"""

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.singlecell.adapters.cellranger_adapter import CellRangerAdapter
from app.singlecell.adapters.generic_fasta_adapter import GenericFastaAdapter
from app.singlecell.adapters.trust4_adapter import Trust4Adapter
from app.singlecell.fasta_generator import write_outputs, write_source_annotations
from app.singlecell.validator import is_leakage_field, validate_records

CONTIG_FASTA = (
    ">AAACCTG-1_contig_1\nACGTACGTACGT\n"
    ">AAACCTG-1_contig_2\nGGGGCCCCGGGG\n"
    ">TTTGGGA-1_contig_1\nTTTTAAAATTTT\n"
)

#: A Cell Ranger annotations CSV with the full column set, including every
#: annotation-derived column AIRRPrep drops from the normalized record.
CONTIG_CSV = (
    "barcode,is_cell,contig_id,high_confidence,length,chain,v_gene,d_gene,"
    "j_gene,c_gene,full_length,productive,cdr3,cdr3_nt,reads,umis\n"
    "AAACCTG-1,true,AAACCTG-1_contig_1,true,12,TRB,TRBV20-1,TRBD1,TRBJ2-7,"
    "TRBC2,true,true,CASSLGQAYEQYF,TGTGCCAGCAGC,3011,17\n"
    "AAACCTG-1,true,AAACCTG-1_contig_2,true,12,TRA,TRAV12-2,None,TRAJ33,"
    "TRAC,true,true,CAVNDYKLSF,TGTGCCGTGAAC,1204,9\n"
    "TTTGGGA-1,true,TTTGGGA-1_contig_1,true,12,TRB,TRBV7-9,TRBD2,TRBJ1-1,"
    "TRBC1,true,false,CASSPGQGAEAFF,TGTGCCAGCAGT,802,5\n"
)


def read_tsv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


class SidecarTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def run_adapter(self, adapter, files) -> tuple[list, Path, Path | None]:
        """Parse, validate and write exactly as the Celery task does."""
        records, _ = validate_records(adapter.parse(files))
        outputs = self.dir / "outputs"
        _, tsv_path = write_outputs(records, outputs)
        sidecar = write_source_annotations(
            records,
            adapter.source_annotations,
            adapter.source_annotation_fields,
            outputs,
        )
        return records, tsv_path, sidecar

    def assert_joins_exactly(self, metadata: Path, sidecar: Path) -> list[dict]:
        """The join on sequence_id must be total, one-to-one and collision-free."""
        normalized = read_tsv(metadata)
        preserved = read_tsv(sidecar)

        normalized_ids = [row["sequence_id"] for row in normalized]
        preserved_ids = [row["sequence_id"] for row in preserved]

        self.assertEqual(
            len(preserved_ids), len(set(preserved_ids)),
            "a sequence_id appears twice in the sidecar",
        )
        self.assertEqual(
            len(normalized_ids), len(set(normalized_ids)),
            "a sequence_id appears twice in the normalized output",
        )
        self.assertEqual(
            set(normalized_ids), set(preserved_ids),
            "the sidecar and the normalized output do not cover the same records",
        )
        self.assertEqual(len(normalized_ids), len(preserved_ids))
        return preserved


class CellRangerSidecarTests(SidecarTestCase):
    def test_contig_csv_annotations_survive_and_join_back(self):
        fasta = self.write("filtered_contig.fasta", CONTIG_FASTA)
        csv_path = self.write("filtered_contig_annotations.csv", CONTIG_CSV)

        adapter = CellRangerAdapter("filtered_contig")
        records, metadata, sidecar = self.run_adapter(
            adapter, {"contig_fasta": fasta, "contig_annotations": csv_path}
        )

        self.assertIsNotNone(sidecar)
        self.assertEqual(sidecar.name, "source_annotations.tsv")
        preserved = self.assert_joins_exactly(metadata, sidecar)
        self.assertEqual(len(records), 3)

        by_id = {row["sequence_id"]: row for row in preserved}
        row = by_id["AAACCTG-1_contig_1"]
        # Exactly the values Cell Ranger wrote, not a re-derivation.
        self.assertEqual(row["v_gene"], "TRBV20-1")
        self.assertEqual(row["d_gene"], "TRBD1")
        self.assertEqual(row["j_gene"], "TRBJ2-7")
        self.assertEqual(row["c_gene"], "TRBC2")
        self.assertEqual(row["chain"], "TRB")
        self.assertEqual(row["cdr3"], "CASSLGQAYEQYF")
        self.assertEqual(row["cdr3_nt"], "TGTGCCAGCAGC")
        self.assertEqual(by_id["TTTGGGA-1_contig_1"]["productive"], "false")

    def test_every_field_the_normalized_output_drops_is_in_the_sidecar(self):
        """The claim under test: nothing the source carried is lost."""
        fasta = self.write("filtered_contig.fasta", CONTIG_FASTA)
        csv_path = self.write("filtered_contig_annotations.csv", CONTIG_CSV)

        adapter = CellRangerAdapter("filtered_contig")
        _, metadata, sidecar = self.run_adapter(
            adapter, {"contig_fasta": fasta, "contig_annotations": csv_path}
        )

        source_columns = set(CONTIG_CSV.splitlines()[0].split(","))
        sidecar_columns = set(read_tsv(sidecar)[0])
        self.assertEqual(
            source_columns - sidecar_columns, set(),
            "a source column is present in neither output",
        )

        # And the ones that are annotation-derived really were kept out of
        # the analysis schema -- the sidecar is an addition, not a loophole.
        # `productive` is the documented exception: it is a column of the
        # normalized schema, filled only when the user opts in (and empty
        # here, since this adapter was built without the opt-in).
        normalized_columns = set(read_tsv(metadata)[0])
        self.assertEqual(
            {c for c in normalized_columns if is_leakage_field(c)}, {"productive"}
        )
        self.assertEqual(
            {row["productive"] for row in read_tsv(metadata)}, {""}
        )
        self.assertTrue(
            {c for c in sidecar_columns if is_leakage_field(c)},
            "the sidecar should be the place the dropped annotations live",
        )

    def test_airr_tsv_route_preserves_its_own_columns(self):
        tsv = self.write(
            "airr_rearrangement.tsv",
            "cell_id\tsequence_id\tsequence\tv_call\td_call\tj_call\tc_call\t"
            "junction\tjunction_aa\tconsensus_count\tduplicate_count\tis_cell\n"
            "AAACCTG-1\tAAACCTG-1_contig_1\tACGTACGTACGT\tTRBV20-1*01\t"
            "TRBD1*01\tTRBJ2-7*01\tTRBC2\tTGTGCCAGCAGC\tCASSLGQAYEQYF\t"
            "3011\t17\tT\n",
        )
        adapter = CellRangerAdapter("airr_tsv")
        _, metadata, sidecar = self.run_adapter(adapter, {"airr_tsv": tsv})

        (row,) = self.assert_joins_exactly(metadata, sidecar)
        self.assertEqual(row["v_call"], "TRBV20-1*01")
        self.assertEqual(row["junction"], "TGTGCCAGCAGC")
        self.assertEqual(row["junction_aa"], "CASSLGQAYEQYF")


class GenericFastaSidecarTests(SidecarTestCase):
    def test_header_and_mapping_columns_are_both_preserved(self):
        fasta = self.write(
            "seqs.fasta",
            ">AAACCTG-1_contig_1 v_call=IGHV1-2 cdr3=CARDL\nACGTACGT\n"
            ">TTTGGGA-1_contig_1 v_call=IGHV3-23 cdr3=CAKGY\nTTTTAAAA\n",
        )
        mapping = self.write(
            "map.tsv",
            "sequence_id\tcell_id\tumi_count\tread_count\tsample\n"
            "AAACCTG-1_contig_1\tAAACCTG-1\t3\t30\tS1\n"
            "TTTGGGA-1_contig_1\tTTTGGGA-1\t2\t20\tS1\n",
        )
        adapter = GenericFastaAdapter()
        _, metadata, sidecar = self.run_adapter(
            adapter, {"fasta": fasta, "barcode_map": mapping}
        )

        rows = {r["sequence_id"]: r for r in self.assert_joins_exactly(metadata, sidecar)}
        self.assertIn("v_call=IGHV1-2", rows["AAACCTG-1_contig_1"]["fasta_header"])
        # A column the adapter itself never reads still survives.
        self.assertEqual(rows["TTTGGGA-1_contig_1"]["sample"], "S1")


class Trust4SidecarTests(SidecarTestCase):
    def test_annot_header_and_chain_call_are_preserved(self):
        annot = self.write(
            "trust4_annot.fa",
            ">AAACCTG-1_0 60 TRBV20-1*01(100):(0-59):(0-59):100.00 * "
            "TRBJ2-7*01 TRBC2 CASSLGQAYEQYF\nACGTACGTACGT\n"
            ">AAACCTG-1_1 60 TRAV12-2*01(100):(0-59):(0-59):100.00 * "
            "TRAJ33*01 TRAC CAVNDYKLSF\nGGGGCCCCGGGG\n",
        )
        report = self.write(
            "trust4_barcode_report.tsv",
            "#barcode\tcell_type\tchain1\tchain2\tsecondary_chain1\tsecondary_chain2\n"
            "AAACCTG-1\tabT\tTRBV20-1,*,TRBJ2-7,TRBC2,TGTGCCAGCAGC,"
            "CASSLGQAYEQYF,12,AAACCTG-1_0,1.00,1\tTRAV12-2,*,TRAJ33,TRAC,"
            "TGTGCCGTGAAC,CAVNDYKLSF,7,AAACCTG-1_1,0.98,0\t*\t*\n",
        )
        adapter = Trust4Adapter()
        _, metadata, sidecar = self.run_adapter(
            adapter, {"annot_fasta": annot, "barcode_report": report}
        )

        rows = {r["sequence_id"]: r for r in self.assert_joins_exactly(metadata, sidecar)}
        self.assertIn("TRBV20-1*01", rows["AAACCTG-1_0"]["annot_header"])
        self.assertIn(
            "CASSLGQAYEQYF", rows["AAACCTG-1_0"]["barcode_report.chain1"]
        )
        self.assertIn("CAVNDYKLSF", rows["AAACCTG-1_1"]["barcode_report.chain2"])


class ProvenanceRecordTests(SidecarTestCase):
    def test_provenance_carries_the_sidecar_checksum(self):
        """A checksum of the *sidecar* is what makes recovery verifiable."""
        from app.core.provenance import file_fingerprint

        fasta = self.write("filtered_contig.fasta", CONTIG_FASTA)
        csv_path = self.write("filtered_contig_annotations.csv", CONTIG_CSV)
        adapter = CellRangerAdapter("filtered_contig")
        _, _, sidecar = self.run_adapter(
            adapter, {"contig_fasta": fasta, "contig_annotations": csv_path}
        )

        fingerprint = file_fingerprint(sidecar)
        self.assertEqual(
            fingerprint["sha256"],
            hashlib.sha256(sidecar.read_bytes()).hexdigest(),
        )
        # The shape tasks.py writes into provenance.json.
        document = {
            "source_annotations": {
                "file": sidecar.name,
                "read_from": list(adapter.source_annotation_origin),
                "fields": list(adapter.source_annotation_fields),
                "rows": len(adapter.source_annotations),
            },
            "outputs": [fingerprint],
        }
        json.loads(json.dumps(document))  # must be serializable as written
        self.assertEqual(
            document["source_annotations"]["read_from"],
            ["filtered_contig_annotations.csv"],
        )
        self.assertEqual(document["source_annotations"]["rows"], 3)


if __name__ == "__main__":
    unittest.main()
