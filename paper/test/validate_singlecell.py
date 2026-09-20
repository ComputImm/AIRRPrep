"""
Record-level validation of AIRRPrep's single-cell adapters on public 10x data
(Supplementary Tables S6 and S7).

Runs the adapters exactly as the Celery task does (adapter.parse ->
validate_records -> write_outputs), then re-reads the written final.fasta and
metadata.tsv and compares them with the source files parsed *independently*
here -- not through the adapter code -- reporting counts rather than a PASS
label:

  matched / missing / additional / sequence-altered records,
  duplicate output ids, cell-barcode mismatches,
  per-field metadata mismatches (UMI, reads, is_cell, high_confidence, productive),
  empty values per output field, annotation columns leaked into the output,
  SHA-256 of every input and output file.

It also runs the generic-FASTA cases, including the negative ones that must be
refused (no barcode rule; a mapping file that misses a sequence).

    cd paper/test
    ../../presto-backend/venv/Scripts/python.exe validate_singlecell.py

Inputs (10x Genomics public dataset sc5p_v2_hs_PBMC_10k, T-cell V(D)J):
    sc5p_v2_hs_PBMC_10k_t_all_contig.fasta / _all_contig_annotations.csv
    sc5p_v2_hs_PBMC_10k_t_filtered_contig.fasta / _filtered_contig_annotations.csv
    sc5p_v2_hs_PBMC_10k_t_airr_rearrangement.tsv

Writes validation_output/<case>/{final.fasta,metadata.tsv} and
validation_report.json / validation_report.tsv next to this script.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent / "presto-backend"
sys.path.insert(0, str(BACKEND))

from app.singlecell.adapters.cellranger_adapter import CellRangerAdapter  # noqa: E402
from app.singlecell.adapters.generic_fasta_adapter import GenericFastaAdapter  # noqa: E402
from app.singlecell.errors import SingleCellAdapterError  # noqa: E402
from app.singlecell.fasta_generator import (  # noqa: E402
    write_outputs,
    write_source_annotations,
)
from app.singlecell.models import UnifiedRecord  # noqa: E402
from app.singlecell.validator import is_leakage_field, validate_records  # noqa: E402

PREFIX = "sc5p_v2_hs_PBMC_10k_t_"
OUT = HERE / "validation_output"
FIELDS = list(UnifiedRecord.model_fields)


def header_columns(path: Path, delimiter: str) -> list[str]:
    """The column names a source table declares, in its own order."""
    with path.open(newline="") as fh:
        return next(csv.reader(fh, delimiter=delimiter), [])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def as_bool(value):
    v = (value or "").strip().lower()
    return True if v in ("true", "t") else False if v in ("false", "f") else None


def as_int(value):
    v = (value or "").strip()
    return int(float(v)) if v else None


def read_fasta(path: Path) -> dict[str, str]:
    seqs, name, parts = {}, None, []
    with path.open() as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith(">"):
                if name is not None:
                    seqs[name] = "".join(parts)
                name, parts = line[1:].split()[0], []
            elif line:
                parts.append(line)
    if name is not None:
        seqs[name] = "".join(parts)
    return seqs


def fasta_headers_with_extra_text(path: Path) -> int:
    with path.open() as fh:
        return sum(1 for line in fh if line.startswith(">") and len(line[1:].split()) > 1)


# --- source truth, parsed independently of the adapters --------------------

def truth_contig_csv(fasta: Path, csv_path: Path) -> dict[str, dict]:
    seqs = read_fasta(fasta)
    truth = {}
    with csv_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            cid = row["contig_id"]
            truth[cid] = {
                "sequence": seqs.get(cid),
                "cell_id": row["barcode"],
                "umi_count": as_int(row["umis"]),
                "read_count": as_int(row["reads"]),
                "is_cell": as_bool(row["is_cell"]),
                "high_confidence": as_bool(row["high_confidence"]),
                "productive": as_bool(row["productive"]),
            }
    return truth


def truth_airr_tsv(tsv: Path) -> dict[str, dict]:
    truth = {}
    with tsv.open(newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            truth[row["sequence_id"]] = {
                "sequence": row["sequence"],
                "cell_id": row["cell_id"],
                # Cell Ranger's AIRR export: duplicate_count = UMIs,
                # consensus_count = reads (checked against the contig CSV).
                "umi_count": as_int(row["duplicate_count"]),
                "read_count": as_int(row["consensus_count"]),
                "is_cell": as_bool(row["is_cell"]),
                "high_confidence": None,  # not a column of this file
                "productive": as_bool(row["productive"]),
            }
    return truth


# --- running an adapter the way the Celery task does -------------------------

def run(adapter, files: dict[str, Path], case: str):
    records = adapter.parse(files)
    records, warnings = validate_records(records)
    fasta, tsv = write_outputs(records, OUT / case)
    sidecar = write_source_annotations(
        records,
        adapter.source_annotations,
        adapter.source_annotation_fields,
        OUT / case,
    )
    return fasta, tsv, sidecar, [*adapter.warnings, *warnings], adapter.parse_report


def check_sidecar_join(sidecar: Path | None, output_ids: set[str], source_columns) -> dict:
    """Is source_annotations.tsv a lossless, collision-free join partner?

    The claim under test is that the annotation fields the normalized output
    omits are preserved rather than destroyed, and can be put back beside the
    record they belong to. That is only true if every output record has
    exactly one sidecar row, no identifier appears twice, and the columns the
    source carried are actually there.
    """
    if sidecar is None:
        return {"written": False}
    with sidecar.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        columns = reader.fieldnames or []
        rows = list(reader)
    ids = [r["sequence_id"] for r in rows]
    unique = set(ids)
    kept = [c for c in source_columns if c in columns]
    return {
        "written": True,
        "file": sidecar.name,
        "rows": len(rows),
        "distinct_ids": len(unique),
        "duplicate_ids": len(ids) - len(unique),
        "rows_without_a_normalized_record": len(unique - output_ids),
        "normalized_records_without_a_row": len(output_ids - unique),
        "columns": len(columns) - 1,
        "source_columns_preserved": f"{len(kept)}/{len(source_columns)}",
        "source_columns_missing": sorted(set(source_columns) - set(columns)),
        "annotation_columns_preserved": sorted(c for c in columns if is_leakage_field(c)),
        "sha256": sha256(sidecar),
    }


def read_outputs(fasta: Path, tsv: Path):
    seqs = read_fasta(fasta)
    with tsv.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        columns = reader.fieldnames or []
        rows = list(reader)
    return seqs, columns, rows


def compare(case, truth, fasta, tsv, compared_fields, warnings, parse_report,
            inputs, sidecar=None, source_columns=()):
    seqs, columns, rows = read_outputs(fasta, tsv)
    meta = {}
    duplicates = 0
    for row in rows:
        if row["sequence_id"] in meta:
            duplicates += 1
        meta[row["sequence_id"]] = row

    out_ids, src_ids = set(meta), set(truth)
    shared = out_ids & src_ids
    result = {
        "case": case,
        "source_records": len(truth),
        "output_records": len(rows),
        "output_cells": len({r["cell_id"] for r in rows}),
        "matched": len(shared),
        "missing": len(src_ids - out_ids),
        "additional": len(out_ids - src_ids),
        "fasta_tsv_id_disagreement": len(set(seqs) ^ out_ids),
        "duplicate_ids": duplicates,
        "sequence_altered": sum(seqs.get(i) != truth[i]["sequence"] for i in shared),
        "cell_id_mismatch": sum(meta[i]["cell_id"] != truth[i]["cell_id"] for i in shared),
        "leaked_annotation_columns": sum(is_leakage_field(c) for c in columns if c != "productive"),
        "unexpected_columns": sorted(set(columns) - set(FIELDS)),
        "fasta_headers_with_extra_text": fasta_headers_with_extra_text(fasta),
        "warnings": len(warnings),
        "parse_report": parse_report,
    }
    for field in compared_fields:
        conv = as_int if field in ("umi_count", "read_count") else as_bool
        result[f"{field}_mismatch"] = sum(
            conv(meta[i][field]) != truth[i][field] for i in shared
        )
    result["empty_values"] = {f: sum(1 for r in rows if r[f] == "") for f in FIELDS}
    result["inputs"] = {role: {"file": p.name, "size_bytes": p.stat().st_size, "sha256": sha256(p)}
                        for role, p in inputs.items()}
    result["outputs"] = {p.name: sha256(p) for p in (fasta, tsv) }
    if sidecar is not None:
        result["outputs"][sidecar.name] = sha256(sidecar)
    join = check_sidecar_join(sidecar, out_ids, list(source_columns))
    result["source_annotations"] = join
    failures = [k for k in ("missing", "additional", "duplicate_ids", "sequence_altered",
                            "cell_id_mismatch", "leaked_annotation_columns",
                            "fasta_headers_with_extra_text", "fasta_tsv_id_disagreement")
                if result[k]]
    failures += [f"{f}_mismatch" for f in compared_fields if result[f"{f}_mismatch"]]
    if result["unexpected_columns"]:
        failures.append("unexpected_columns")
    if join.get("written"):
        failures += [k for k in ("duplicate_ids",
                                 "rows_without_a_normalized_record",
                                 "normalized_records_without_a_row")
                     if join[k]]
        if join["source_columns_missing"]:
            failures.append("source_columns_missing")
    result["discrepancies"] = failures
    return result


def expect_refusal(case, adapter, files):
    try:
        adapter.parse(files)
    except SingleCellAdapterError as e:
        return {"case": case, "expected": "refused", "observed": "refused", "message": str(e),
                "discrepancies": []}
    return {"case": case, "expected": "refused", "observed": "accepted",
            "discrepancies": ["accepted input that must be refused"]}


def main():
    files = {k: HERE / f"{PREFIX}{k}" for k in (
        "all_contig.fasta", "all_contig_annotations.csv",
        "filtered_contig.fasta", "filtered_contig_annotations.csv",
        "airr_rearrangement.tsv")}
    missing = [p.name for p in files.values() if not p.is_file()]
    if missing:
        sys.exit(f"Missing input files: {missing}")

    contig_fields = ["umi_count", "read_count", "is_cell", "high_confidence", "productive"]
    results = []

    for variant, label in (("all_contig", "cellranger_all_contig"),
                           ("filtered_contig", "cellranger_filtered_contig")):
        inputs = {"contig_fasta": files[f"{variant}.fasta"],
                  "contig_annotations": files[f"{variant}_annotations.csv"]}
        fasta, tsv, sidecar, warnings, report = run(
            CellRangerAdapter(variant, allow_productive=True), inputs, label)
        results.append(compare(label, truth_contig_csv(*inputs.values()), fasta, tsv,
                               contig_fields, warnings, report, inputs,
                               sidecar, header_columns(inputs["contig_annotations"], ",")))

    inputs = {"airr_tsv": files["airr_rearrangement.tsv"]}
    fasta, tsv, sidecar, warnings, report = run(
        CellRangerAdapter("airr_tsv", allow_productive=True), inputs, "cellranger_airr_tsv")
    results.append(compare("cellranger_airr_tsv", truth_airr_tsv(inputs["airr_tsv"]), fasta, tsv,
                           contig_fields, warnings, report, inputs,
                           sidecar, header_columns(inputs["airr_tsv"], "	")))

    # productive is opt-in: without it, every value must be empty.
    fasta, tsv, _, _, _ = run(CellRangerAdapter("filtered_contig"),
                           {"contig_fasta": files["filtered_contig.fasta"],
                            "contig_annotations": files["filtered_contig_annotations.csv"]},
                           "cellranger_filtered_default")
    _, _, rows = read_outputs(fasta, tsv)
    populated = sum(1 for r in rows if r["productive"] != "")
    results.append({"case": "productive_suppressed_by_default", "records": len(rows),
                    "productive_populated": populated,
                    "discrepancies": ["productive populated without opt-in"] if populated else []})

    # Generic FASTA, with the barcode supplied by a mapping file (T4) ...
    truth = truth_contig_csv(files["filtered_contig.fasta"], files["filtered_contig_annotations.csv"])
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = OUT / "generic_fasta_barcode_map.tsv"
    with mapping.open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["sequence_id", "cell_id", "umi_count", "read_count"])
        for cid, t in truth.items():
            w.writerow([cid, t["cell_id"], t["umi_count"], t["read_count"]])
    inputs = {"fasta": files["filtered_contig.fasta"], "barcode_map": mapping}
    fasta, tsv, sidecar, warnings, report = run(GenericFastaAdapter(), inputs, "generic_fasta_mapping")
    generic_truth = {k: {**v, "is_cell": None, "high_confidence": None, "productive": None}
                     for k, v in truth.items()}
    results.append(compare("generic_fasta_mapping", generic_truth, fasta, tsv,
                           ["umi_count", "read_count", "is_cell", "high_confidence", "productive"],
                           warnings, report, inputs, sidecar,
                           header_columns(mapping, "	")))

    # ... and by a header regex, where counts are not available.
    inputs = {"fasta": files["filtered_contig.fasta"]}
    fasta, tsv, sidecar, warnings, report = run(
        GenericFastaAdapter(barcode_header_regex=r"^([ACGT]+-\d+)_contig"), inputs, "generic_fasta_regex")
    regex_truth = {k: {**v, "umi_count": None, "read_count": None, "is_cell": None,
                       "high_confidence": None, "productive": None} for k, v in truth.items()}
    results.append(compare("generic_fasta_regex", regex_truth, fasta, tsv,
                           ["umi_count", "read_count", "is_cell", "high_confidence", "productive"],
                           warnings, report, inputs, sidecar,
                           ["fasta_header"]))

    # Negative cases: must be refused, never turned into one cell per sequence.
    results.append(expect_refusal("generic_fasta_no_barcode_rule (T5)", GenericFastaAdapter(),
                                  {"fasta": files["filtered_contig.fasta"]}))
    partial = OUT / "generic_fasta_partial_map.tsv"
    lines = mapping.read_text().splitlines()
    partial.write_text("\n".join(lines[:-1]) + "\n")
    results.append(expect_refusal("generic_fasta_incomplete_mapping", GenericFastaAdapter(),
                                  {"fasta": files["filtered_contig.fasta"], "barcode_map": partial}))

    (HERE / "validation_report.json").write_text(json.dumps(results, indent=2))

    # Flatten the sidecar join into the TSV, so the lossless-provenance claim
    # is readable in the same table as everything else.
    for r in results:
        join = r.get("source_annotations") or {}
        if join.get("written"):
            r["source_annotation_rows"] = join["rows"]
            r["source_annotation_columns"] = join["columns"]
            r["source_rows_unjoinable"] = (
                join["rows_without_a_normalized_record"]
                + join["normalized_records_without_a_row"]
                + join["duplicate_ids"]
            )
            r["source_columns_preserved"] = join["source_columns_preserved"]

    columns = ["case", "source_records", "output_records", "output_cells", "matched", "missing",
               "additional", "sequence_altered", "duplicate_ids", "cell_id_mismatch",
               "umi_count_mismatch", "read_count_mismatch", "is_cell_mismatch",
               "high_confidence_mismatch", "productive_mismatch", "leaked_annotation_columns",
               "source_annotation_rows", "source_annotation_columns",
               "source_rows_unjoinable", "source_columns_preserved",
               "observed", "discrepancies"]
    with (HERE / "validation_report.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(columns)
        for r in results:
            w.writerow([";".join(r[c]) if c == "discrepancies" else r.get(c, "") for c in columns])

    for r in results:
        status = "OK " if not r["discrepancies"] else "BAD"
        detail = {k: r[k] for k in ("source_records", "output_records", "output_cells", "matched",
                                    "missing", "additional", "sequence_altered", "cell_id_mismatch")
                  if k in r}
        print(f"[{status}] {r['case']}: {detail or r.get('observed', '')} {r['discrepancies'] or ''}")
    sys.exit(1 if any(r["discrepancies"] for r in results) else 0)


if __name__ == "__main__":
    main()
