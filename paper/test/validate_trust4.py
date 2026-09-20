"""
Validation of the TRUST4-based single-cell routes (Supplementary Table S7,
T1-T3) on real 10x data, run in a Linux container that provides TRUST4 1.1.9
with its v1.1.9 human references and samtools (paper/test/trust4-test).

Runs the adapters the way the Celery task does (adapter.parse ->
validate_records -> write_outputs + provenance.json) and reports counts:

  T2   raw 10x FASTQ, sc5p_v2_hs_PBMC_1k_b (10x v2, human) -> TRUST4 assembly
  T1   the trust4_annot.fa + trust4_barcode_report.tsv written by T2, uploaded
       as precomputed TRUST4 output (must reproduce T2's barcode-report records)
  T3   Cell Ranger all_contig.bam of the same library, CB/UB tags extracted
       with samtools ("Extract reads with samtools first")
  T4   genome-aligned 5' gene-expression BAM of the same cells (Cell Ranger
       possorted_genome_bam.bam, reads in TRUST4's IG/TCR loci only), assembled
       through TRUST4's genome-coordinate BAM route with CB/UB tags
  T3n1 the same BAM through TRUST4's genome-coordinate BAM route -> must be refused
       (aligned to contigs, not the genome)
  T3n2 TRUST4's simulated example.bam (no CB/UB tags), both BAM routes -> must be refused

Cell barcodes are compared with Cell Ranger's calls on the same library
(test-data/expected/cellranger_cells.txt, 83 B cells), and chains are counted
from the constant-gene call TRUST4 writes in each annot.fa header.

Run it in either image, with the backend code at /app, the repository's
test-data at /data/test-data and paper/test at /data/out -- see
paper/test/trust4-test/run_trust4_tests.sh. TRUST4 works in /work (container
disk); the normalized outputs, provenance.json, TRUST4's annot.fa and barcode
report, and trust4_validation.{json,tsv} are copied to
/data/out/trust4_validation.
"""

import csv
import hashlib
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/app")

from app.singlecell.adapters.bam_adapter import BamAdapter  # noqa: E402
from app.singlecell.adapters.fastq_adapter import FastqAdapter  # noqa: E402
from app.singlecell.adapters.trust4_adapter import Trust4Adapter  # noqa: E402
from app.singlecell.errors import SingleCellAdapterError, SingleCellConfigError  # noqa: E402
from app.singlecell.fasta_generator import write_outputs  # noqa: E402
from app.singlecell.models import Trust4Options  # noqa: E402
from app.singlecell.validator import validate_records  # noqa: E402
from app.core.provenance import file_fingerprint, software_versions  # noqa: E402

DATA = Path("/data/test-data")
WORK = Path("/work/trust4_validation")
OUT = Path("/data/out/trust4_validation")
# Cell Ranger and BAM CB tags carry a "-1" GEM-well suffix; barcodes TRUST4
# reads from R1 do not. Compare with the suffix removed.
BARCODE_RE = re.compile(r"^[ACGT]{16}(-1)?$")
#: TRUST4 1.1.9 fastq-extractor/bam-extractor segfault intermittently (exit 139) on
#: identical input; a case is retried and the number of attempts is recorded.
MAX_ATTEMPTS = 3

R1 = DATA / "raw10x/sc5p_v2_hs_PBMC_1k_b_S1_L001_R1_001.fastq.gz"
R2 = DATA / "raw10x/sc5p_v2_hs_PBMC_1k_b_S1_L001_R2_001.fastq.gz"
CONTIG_BAM = DATA / "raw10x/all_contig.bam"
GENOME_BAM = DATA / "raw10x/sc5p_v2_hs_PBMC_1k_5gex_vdj_loci.bam"
EXAMPLE_BAM = DATA / "trust4-selftest/example.bam"
CELLRANGER_CELLS = DATA / "expected/cellranger_cells.txt"
CELLRANGER_CONTIGS = DATA / "cellranger/filtered_contig_annotations.csv"
LOCUS_RE = re.compile(r"(IG[HKL]|TR[ABDG])")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: Path) -> dict:
    return {"file": path.name, "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def chain_of(header: str) -> str | None:
    """IGH/IGK/IGL/TRA/TRB/... from the first gene call in an annot.fa header."""
    m = re.search(r"\b(IG[HKL]|TR[ABDG])[VDJC]", header)
    return m.group(1) if m else None


def annot_chains(annot: Path) -> dict[str, str]:
    chains = {}
    with annot.open() as fh:
        for line in fh:
            if line.startswith(">"):
                parts = line[1:].split()
                chains[parts[0]] = chain_of(line) or "unassigned"
    return chains


def summarize(case, records, adapter, warnings, trust4_dir, seconds, reference_cells,
              adapter_annot=None):
    cells = {r.cell_id for r in records}
    annot = trust4_dir / "trust4_annot.fa" if trust4_dir else adapter_annot
    chains = annot_chains(annot) if annot else {}
    chain_counts: dict[str, int] = {}
    for r in records:
        c = chains.get(r.sequence_id, "unassigned")
        chain_counts[c] = chain_counts.get(c, 0) + 1
    per_cell: dict[str, int] = {}
    for r in records:
        per_cell[r.cell_id] = per_cell.get(r.cell_id, 0) + 1
    shared = {c.removesuffix("-1") for c in cells} & {c.removesuffix("-1") for c in reference_cells}
    return {
        "case": case,
        "outcome": "accepted",
        "seconds": round(seconds, 1),
        "parse_report": adapter.parse_report,
        "records": len(records),
        "cells": len(cells),
        "cell_ids_not_barcode_shaped": sum(1 for c in cells if not BARCODE_RE.match(c)),
        "cell_ids_equal_to_a_sequence_id": sum(1 for r in records if r.cell_id == r.sequence_id),
        "contigs_per_cell_median": sorted(per_cell.values())[len(per_cell) // 2] if per_cell else 0,
        "chains": dict(sorted(chain_counts.items())),
        "cellranger_cells": len(reference_cells),
        "cellranger_cells_recovered": len(shared),
        "warnings": warnings,
    }


def cdr3_concordance(barcode_report: Path) -> dict:
    """
    Agreement of TRUST4's per-cell calls with Cell Ranger's on the same library.

    For every (cell, locus) pair Cell Ranger calls in its filtered,
    high-confidence contigs, is the same CDR3 nucleotide sequence among
    TRUST4's chains of that locus for that barcode? The "-1" GEM-well suffix
    is ignored.
    """
    truth: dict[str, dict[str, set]] = {}
    with CELLRANGER_CONTIGS.open(newline="") as fh:
        for row in csv.DictReader(fh):
            cell = truth.setdefault(row["barcode"].removesuffix("-1"), {})
            cell.setdefault(row["chain"], set()).add(row["cdr3_nt"])

    calls: dict[str, dict[str, set]] = {}
    with barcode_report.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            cell = calls.setdefault((row.get("#barcode") or "").removesuffix("-1"), {})
            for key in ("chain1", "chain2", "secondary_chain1", "secondary_chain2"):
                for chain in (row.get(key) or "*").split(";"):
                    fields = chain.split(",")
                    if len(fields) < 6:
                        continue
                    gene = next((g for g in (fields[0], fields[2], fields[3]) if g not in ("*", "")), "")
                    locus = LOCUS_RE.match(gene)
                    if locus:
                        cell.setdefault(locus.group(1), set()).add(fields[4])

    pairs = matched = heavy = heavy_matched = light = light_matched = paired = paired_matched = 0
    for barcode, loci in truth.items():
        found = calls.get(barcode, {})
        for locus, cdr3s in loci.items():
            pairs += 1
            matched += bool(cdr3s & found.get(locus, set()))
        h, th = loci.get("IGH", set()), found.get("IGH", set())
        lt = loci.get("IGK", set()) | loci.get("IGL", set())
        tl = found.get("IGK", set()) | found.get("IGL", set())
        heavy += bool(h)
        heavy_matched += bool(h & th)
        light += bool(lt)
        light_matched += bool(lt & tl)
        if h and lt:
            paired += 1
            paired_matched += bool(h & th) and bool(lt & tl)
    return {
        "cellranger_cells": len(truth),
        "cellranger_cells_called_by_trust4": sum(1 for b in truth if b in calls),
        "cell_locus_pairs": pairs,
        "cell_locus_pairs_with_identical_cdr3": matched,
        "cells_with_heavy_chain": heavy,
        "heavy_identical": heavy_matched,
        "cells_with_light_chain": light,
        "light_identical": light_matched,
        "cells_with_both": paired,
        "both_identical": paired_matched,
    }


def write_provenance(outputs_dir, adapter, files, records, warnings, outputs):
    """Same content as app.singlecell.tasks._write_provenance, without Celery."""
    document = {
        "schema": "airrprep.singlecell.normalized",
        "schema_version": 1,
        "fields": list(records[0].model_fields) if records else [],
        "format_id": adapter.format_id,
        "created_at": time.time(),
        "software": software_versions(),
        "inputs": [{"role": role, **file_fingerprint(path)} for role, path in sorted(files.items())],
        "options": {"trust4_options": adapter.options.model_dump() if hasattr(adapter, "options") else None},
        "parse_report": adapter.parse_report,
        "records": len(records),
        "cells": len({r.cell_id for r in records}),
        "warnings": warnings,
        "outputs": [file_fingerprint(p) for p in outputs],
    }
    (outputs_dir / "provenance.json").write_text(json.dumps(document, indent=2), encoding="utf-8")


def run_accepting(case, make_adapter, files, reference_cells):
    case_dir = WORK / case
    crashes = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        shutil.rmtree(case_dir, ignore_errors=True)
        adapter = make_adapter()
        t0 = time.time()
        try:
            records = adapter.parse(files)
            break
        except SingleCellConfigError as e:
            if "failed: 139" not in str(e) or attempt == MAX_ATTEMPTS:
                raise
            crashes.append(str(e)[-160:])
            print(f"    attempt {attempt}: TRUST4 segfault (exit 139), retrying", flush=True)
    records, warnings = validate_records(records)
    warnings = [*adapter.warnings, *warnings]
    seconds = time.time() - t0
    fasta, tsv = write_outputs(records, case_dir / "outputs")
    write_provenance(case_dir / "outputs", adapter, files, records, warnings, [fasta, tsv])
    trust4_dir = case_dir / "trust4" if (case_dir / "trust4" / "trust4_annot.fa").is_file() else None
    result = summarize(case, records, adapter, warnings, trust4_dir, seconds, reference_cells,
                       adapter_annot=files.get("annot_fasta"))
    result["inputs"] = {role: fingerprint(p) for role, p in files.items()}
    report_file = (trust4_dir / "trust4_barcode_report.tsv") if trust4_dir else files.get("barcode_report")
    if report_file and report_file.is_file():
        result["cdr3_concordance_with_cellranger"] = cdr3_concordance(report_file)
    result["barcodes_with_N"] = sum(1 for c in {r.cell_id for r in records} if "N" in c)
    result["attempts"] = len(crashes) + 1
    result["trust4_segfaults_before_success"] = len(crashes)

    # Keep the small results beside the repository; intermediates stay in /work.
    keep = OUT / case
    shutil.copytree(case_dir / "outputs", keep / "outputs", dirs_exist_ok=True)
    if trust4_dir:
        (keep / "trust4").mkdir(parents=True, exist_ok=True)
        for name in ("trust4_annot.fa", "trust4_barcode_report.tsv", "trust4_barcode_airr.tsv", "trust4_report.tsv"):
            if (trust4_dir / name).is_file():
                shutil.copy2(trust4_dir / name, keep / "trust4" / name)
        result["trust4_outputs"] = {
            name: fingerprint(trust4_dir / name)
            for name in ("trust4_annot.fa", "trust4_barcode_report.tsv", "trust4_barcode_airr.tsv")
            if (trust4_dir / name).is_file()
        }
    return result, records


def run_refusing(case, make_adapter, files):
    t0 = time.time()
    try:
        adapter = make_adapter()
        adapter.validate(files)  # the pre-flight a job launch performs
        adapter.parse(files)
    except (SingleCellAdapterError, SingleCellConfigError) as e:
        return {"case": case, "expected": "refused", "outcome": "refused",
                "seconds": round(time.time() - t0, 1), "message": str(e)[:600]}
    return {"case": case, "expected": "refused", "outcome": "ACCEPTED",
            "seconds": round(time.time() - t0, 1)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    reference_cells = set(CELLRANGER_CELLS.read_text().split())
    results = []
    options = Trust4Options(species="human", chemistry="10x_v2")

    selected = set(sys.argv[1:])

    def guarded(case, fn):
        if selected and case not in selected:
            return None
        print(f"--- {case}", flush=True)
        try:
            out = fn()
        except Exception as e:  # recorded, not hidden
            out = {"case": case, "outcome": "ERROR", "message": f"{type(e).__name__}: {e}"[:1500],
                   "traceback": traceback.format_exc()[-3000:]}
        print(json.dumps({k: v for k, v in out.items() if k not in ("traceback", "warnings")}, indent=1)[:2500], flush=True)
        results.append(out)
        return out

    # T2: raw 10x FASTQ -> TRUST4
    t2_records = {}

    def t2():
        res, recs = run_accepting("T2_fastq_10x",
                                  lambda: FastqAdapter(options=options, work_dir=WORK / "T2_fastq_10x"),
                                  {"r1_fastq": R1, "r2_fastq": R2}, reference_cells)
        t2_records["records"] = recs
        return res

    guarded("T2_fastq_10x", t2)

    # T1: T2's TRUST4 files uploaded as precomputed output
    def t1():
        trust4_dir = WORK / "T2_fastq_10x" / "trust4"
        files = {"annot_fasta": trust4_dir / "trust4_annot.fa",
                 "barcode_report": trust4_dir / "trust4_barcode_report.tsv"}
        # T2's files are copied aside first: run_accepting clears T1's own work dir only.
        res, recs = run_accepting("T1_trust4_upload", Trust4Adapter, files, reference_cells)
        by_id_t1 = {(r.sequence_id, r.cell_id, r.sequence) for r in recs}
        by_id_t2 = {(r.sequence_id, r.cell_id, r.sequence) for r in t2_records.get("records", [])}
        res["agreement_with_T2"] = {
            "T1_records": len(by_id_t1),
            "T2_records": len(by_id_t2),
            "identical_records": len(by_id_t1 & by_id_t2),
            "only_in_T1": len(by_id_t1 - by_id_t2),
            "only_in_T2": len(by_id_t2 - by_id_t1),
        }
        return res

    if t2_records.get("records") is not None or (selected and "T1_trust4_upload" in selected):
        guarded("T1_trust4_upload", t1)

    # T3: Cell Ranger BAM through the samtools route
    def t3():
        opts = Trust4Options(species="human", chemistry="10x_v2", bam_extract_with_samtools=True)
        res, _ = run_accepting("T3_bam_samtools",
                               lambda: BamAdapter(options=opts, work_dir=WORK / "T3_bam_samtools"),
                               {"bam": CONTIG_BAM}, reference_cells)
        res["bam_tag_counts"] = {k: res["parse_report"].get(k) for k in ("reads", "reads_with_barcode", "reads_with_umi", "paired")}
        return res

    guarded("T3_bam_samtools", t3)

    # T4: genome-aligned 10x BAM through TRUST4's own BAM reader (CB/UB tags)
    def t4():
        res, _ = run_accepting("T4_bam_genome",
                               lambda: BamAdapter(options=options, work_dir=WORK / "T4_bam_genome"),
                               {"bam": GENOME_BAM}, reference_cells)
        return res

    guarded("T4_bam_genome", t4)

    # Negative BAM cases
    guarded("T3n1_contig_bam_genome_route", lambda: run_refusing(
        "T3n1_contig_bam_genome_route",
        lambda: BamAdapter(options=options, work_dir=WORK / "T3n1"), {"bam": CONTIG_BAM}))
    guarded("T3n2_example_bam_genome_route", lambda: run_refusing(
        "T3n2_example_bam_genome_route",
        lambda: BamAdapter(options=options, work_dir=WORK / "T3n2"), {"bam": EXAMPLE_BAM}))
    guarded("T3n3_example_bam_samtools_route", lambda: run_refusing(
        "T3n3_example_bam_samtools_route",
        lambda: BamAdapter(options=Trust4Options(species="human", bam_extract_with_samtools=True),
                           work_dir=WORK / "T3n3"), {"bam": EXAMPLE_BAM}))

    report_path = OUT / "trust4_validation.json"
    if selected and report_path.is_file():
        previous = json.loads(report_path.read_text())["results"]
        fresh = {r["case"] for r in results}
        order = [r["case"] for r in previous] + [c for c in (r["case"] for r in results) if c not in {p["case"] for p in previous}]
        merged = {r["case"]: r for r in previous}
        merged.update({r["case"]: r for r in results})
        results = [merged[c] for c in order if c in merged]
    report = {"software": software_versions(), "results": results}
    (OUT / "trust4_validation.json").write_text(json.dumps(report, indent=2, default=str))
    cols = ["case", "outcome", "seconds", "records", "cells", "cellranger_cells_recovered",
            "cell_ids_not_barcode_shaped", "cell_ids_equal_to_a_sequence_id", "chains", "message"]
    with (OUT / "trust4_validation.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols)
        for r in results:
            w.writerow([json.dumps(r[c]) if isinstance(r.get(c), dict) else r.get(c, "") for c in cols])
    bad = [r["case"] for r in results
           if r.get("outcome") in ("ERROR", "ACCEPTED")]
    print("FAILED CASES:", bad if bad else "none")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
