# -*- coding: utf-8 -*-
"""
Record-level comparison of AIRRPrep and CLI-pRESTO outputs, step by step.

compare_outputs.py only compares record *counts*. This compares the records
themselves: for every step, both sides' pass files are parsed and matched by
sequence identifier, and each matched record is checked for an identical
nucleotide sequence, quality string and annotation set. Annotations are
compared as a multiset of key/value pairs, so a harmless reordering of header
fields is not reported as a difference but a repeated field is; record order in
the file is reported separately (as is byte identity) but does not count as a
mismatch.

    python compare_records.py            # all three workflows
    python compare_records.py race325275 # one

Writes records_verified.txt and records_verified.json next to this script.
"""

import hashlib
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
BACKEND = BENCH.parent.parent
RESULTS = json.loads((BENCH / "results.json").read_text())

# (step label, CLI file(s), AIRRPrep step-dir glob(s)); a PairSeq step has one
# file per mate, compared mate by mate. "table" is the final annotation table.
STEPS = {
    "race325275": ("cli/race325275/run", [
        ("1  FilterSeq.quality R1", ["HD09N-R1_quality-pass.fastq"], ["01/*_R1.fastq"]),
        ("2  FilterSeq.quality R2", ["HD09N-R2_quality-pass.fastq"], ["02/*_R2.fastq"]),
        ("3  MaskPrimers.score R1", ["HD09N-R1_primers-pass.fastq"], ["03/*_R1.fastq"]),
        ("4  MaskPrimers.score R2", ["HD09N-R2_primers-pass.fastq"], ["04/*_R2.fastq"]),
        ("5  PairSeq", ["HD09N-R1_primers-pass_pair-pass.fastq", "HD09N-R2_primers-pass_pair-pass.fastq"],
         ["05/*_R1_pair-pass.fastq", "05/*_R2_pair-pass.fastq"]),
        ("6  BuildConsensus R1", ["HD09N-R1_consensus-pass.fastq"], ["06/*_R1.fastq"]),
        ("7  BuildConsensus R2", ["HD09N-R2_consensus-pass.fastq"], ["07/*_R2.fastq"]),
        ("8  PairSeq", ["HD09N-R1_consensus-pass_pair-pass.fastq", "HD09N-R2_consensus-pass_pair-pass.fastq"],
         ["08/*_R1_pair-pass.fastq", "08/*_R2_pair-pass.fastq"]),
        ("9  AssemblePairs.sequential", ["HD09N-C_assemble-pass.fastq"], ["09/*_assembled.fastq"]),
        ("10 MaskPrimers.align", ["HD09N-C_primers-pass.fastq"], ["10/*_R1.fastq"]),
        ("11 ParseHeaders.collapse", ["HD09N-C_primers-pass_reheader.fastq"], ["11/*_R1.fastq"]),
        ("12 CollapseSeq", ["HD09N-C_collapse-unique.fastq"], ["12/*_R1.fastq"]),
        ("13 SplitSeq.group", ["HD09N-C_atleast-2.fastq"], ["13/*_atleast-2.fastq"]),
        ("14 ParseHeaders.table", ["HD09N-C_atleast-2_headers.tab"], ["table"]),
    ]),
    "umi2x250": ("cli/umi2x250/run", [
        ("1  FilterSeq.quality R1", ["MS12_R1_quality-pass.fastq"], ["01/*_R1.fastq"]),
        ("2  FilterSeq.quality R2", ["MS12_R2_quality-pass.fastq"], ["02/*_R2.fastq"]),
        ("3  MaskPrimers.score R1", ["MS12_R1_primers-pass.fastq"], ["03/*_R1.fastq"]),
        ("4  MaskPrimers.score R2", ["MS12_R2_primers-pass.fastq"], ["04/*_R2.fastq"]),
        ("5  PairSeq", ["MS12_R1_primers-pass_pair-pass.fastq", "MS12_R2_primers-pass_pair-pass.fastq"],
         ["05/*_R1_pair-pass.fastq", "05/*_R2_pair-pass.fastq"]),
        ("6  BuildConsensus R1", ["MS12_R1_consensus-pass.fastq"], ["06/*_R1.fastq"]),
        ("7  BuildConsensus R2", ["MS12_R2_consensus-pass.fastq"], ["07/*_R2.fastq"]),
        ("8  PairSeq", ["MS12_R1_consensus-pass_pair-pass.fastq", "MS12_R2_consensus-pass_pair-pass.fastq"],
         ["08/*_R1_pair-pass.fastq", "08/*_R2_pair-pass.fastq"]),
        ("9  AssemblePairs.align", ["MS12_assemble-pass.fastq"], ["09/*_assembled.fastq"]),
        ("10 ParseHeaders.collapse", ["MS12_assemble-pass_reheader.fastq"], ["10/*.fastq"]),
        ("11 CollapseSeq", ["MS12_collapse-unique.fastq"], ["11/*.fastq"]),
        ("12 SplitSeq.group", ["MS12_atleast-2.fastq"], ["12/*_atleast-2.fastq"]),
        ("13 ParseHeaders.table", ["MS12_atleast-2_headers.tab"], ["table"]),
    ]),
    "nonumi2x250": ("cli/nonumi2x250/run", [
        ("1  AssemblePairs.align", ["M1_assemble-pass.fastq"], ["01/*_assembled.fastq"]),
        ("2  FilterSeq.quality", ["M1_quality-pass.fastq"], ["02/*.fastq"]),
        ("3  MaskPrimers.score V", ["M1-FWD_primers-pass.fastq"], ["03/*.fastq"]),
        ("4  MaskPrimers.score C", ["M1-REV_primers-pass.fastq"], ["04/*.fastq"]),
        ("5  CollapseSeq", ["M1_collapse-unique.fastq"], ["05/*.fastq"]),
        ("6  SplitSeq.group", ["M1_atleast-2.fastq"], ["06/*_atleast-2.fastq"]),
        ("7  ParseHeaders.table", ["M1_atleast-2_headers.tab"], ["table"]),
    ]),
}


def job_dir(name: str) -> Path:
    last = RESULTS[name]["last_job"]
    return BACKEND / "jobs" / last["session"] / last["job"]


def resolve_airrprep(jd: Path, pattern: str) -> Path:
    if pattern == "table":
        hits = sorted((jd / "outputs").glob("*.tsv"))
    else:
        sub, glob = pattern.split("/", 1)
        hits = sorted(
            p for p in (jd / "steps" / sub).glob(glob)
            if "_fail" not in p.name and "under-" not in p.name
        )
    if len(hits) != 1:
        raise RuntimeError(f"{jd.name}: {pattern} matched {[h.name for h in hits]}")
    return hits[0]


def read_fastq(path: Path) -> list[tuple[str, str, str, dict]]:
    records = []
    with path.open() as fh:
        while True:
            header = fh.readline().rstrip("\n")
            if not header:
                break
            seq = fh.readline().rstrip("\n")
            fh.readline()
            qual = fh.readline().rstrip("\n")
            fields = header[1:].split("|")
            # A multiset of key/value pairs, not a dict: a dict would collapse
            # a repeated annotation field, which is exactly the kind of header
            # defect this comparison has to catch.
            ann = tuple(sorted(
                tuple(f.split("=", 1)) for f in fields[1:] if "=" in f
            ))
            records.append((fields[0], seq, qual, ann))
    return records


def read_table(path: Path) -> list[tuple[str, str, str, dict]]:
    # pRESTO's table writer on Windows ends rows with CR CR LF, which
    # splitlines() turns into an extra blank line after every row.
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    cols = lines[0].split("\t")
    out = []
    for line in lines[1:]:
        values = line.split("\t")
        row = list(zip(cols, values))
        ident = next(v for c, v in row if c == "ID")
        out.append((ident, "", "", tuple(sorted(p for p in row if p[0] != "ID"))))
    return out


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(cli: Path, air: Path) -> dict:
    reader = read_table if cli.suffix == ".tab" else read_fastq
    a, b = reader(cli), reader(air)
    da, db = {r[0]: r for r in a}, {r[0]: r for r in b}
    shared = da.keys() & db.keys()
    result = {
        "cli_records": len(a),
        "airrprep_records": len(b),
        "duplicate_ids_cli": len(a) - len(da),
        "duplicate_ids_airrprep": len(b) - len(db),
        "missing_in_airrprep": len(da.keys() - db.keys()),
        "additional_in_airrprep": len(db.keys() - da.keys()),
        "sequence_differs": sum(da[i][1] != db[i][1] for i in shared),
        "quality_differs": sum(da[i][2] != db[i][2] for i in shared),
        "annotations_differ": sum(da[i][3] != db[i][3] for i in shared),
        "same_order": [r[0] for r in a] == [r[0] for r in b],
        "byte_identical": sha(cli) == sha(air),
    }
    result["identical_records"] = sum(
        da[i][1:] == db[i][1:] for i in shared
    )
    diffs = [i for i in shared if da[i][1:] != db[i][1:]][:3]
    result["example_differences"] = [
        {"id": i, "cli": da[i][3], "airrprep": db[i][3]} for i in diffs
    ]
    return result


def main():
    only = sys.argv[1:] or list(STEPS)
    report, lines = {}, []
    all_ok = True
    for name in only:
        cli_dir, steps = STEPS[name]
        jd = job_dir(name)
        lines += ["=" * 78, f"{name} -- {RESULTS[name]['label']}",
                  f"  AIRRPrep job: {jd.relative_to(BACKEND)}", ""]
        lines.append(f"  {'step':<30}{'records':>9}{'identical':>11}"
                     f"{'missing':>9}{'extra':>7}{'altered':>9}  order bytes")
        report[name] = []
        for label, cli_files, air_patterns in steps:
            for mate, (cf, ap) in enumerate(zip(cli_files, air_patterns), 1):
                r = compare(BENCH / cli_dir / cf, resolve_airrprep(jd, ap))
                altered = max(r["sequence_differs"], r["quality_differs"],
                              r["annotations_differ"])
                ok = (r["missing_in_airrprep"] == 0 and r["additional_in_airrprep"] == 0
                      and r["identical_records"] == r["cli_records"] == r["airrprep_records"])
                all_ok &= ok
                shown = label + (f" (mate {mate})" if len(cli_files) > 1 else "")
                report[name].append({"step": shown, "ok": ok, **r})
                lines.append(
                    f"  {shown:<30}{r['cli_records']:>9,}{r['identical_records']:>11,}"
                    f"{r['missing_in_airrprep']:>9}{r['additional_in_airrprep']:>7}"
                    f"{altered:>9}  {'same' if r['same_order'] else 'DIFF':<5} "
                    f"{'same' if r['byte_identical'] else 'diff'}"
                    + ("" if ok else "   <-- MISMATCH")
                )
        lines.append("")
    lines.append("ALL STEPS RECORD-IDENTICAL" if all_ok else "MISMATCHES FOUND")
    text = "\n".join(lines)
    print(text)
    (BENCH / "records_verified.txt").write_text(text + "\n", encoding="utf-8")
    (BENCH / "records_verified.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
