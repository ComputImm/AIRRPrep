# -*- coding: utf-8 -*-
"""
Record counts produced by each side, step by step.

CLI-pRESTO counts come from the intermediate files the reference script leaves
in its run directory; AIRRPrep counts come from the step_stats the job wrote to
Redis. Both are counted the same way: FASTQ lines/4, table rows = lines - 1.
"""

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent

# Ordered CLI output file per pipeline step, matching the step order of the
# corresponding predefined workflow.
CLI_STEPS = {
    "race325275": [
        ("1  FilterSeq.quality R1",      "HD09N-R1_quality-pass.fastq"),
        ("2  FilterSeq.quality R2",      "HD09N-R2_quality-pass.fastq"),
        ("3  MaskPrimers.score R1",      "HD09N-R1_primers-pass.fastq"),
        ("4  MaskPrimers.score R2",      "HD09N-R2_primers-pass.fastq"),
        ("5  PairSeq",                   "HD09N-R1_primers-pass_pair-pass.fastq"),
        ("6  BuildConsensus R1",         "HD09N-R1_consensus-pass.fastq"),
        ("7  BuildConsensus R2",         "HD09N-R2_consensus-pass.fastq"),
        ("8  PairSeq",                   "HD09N-R1_consensus-pass_pair-pass.fastq"),
        ("9  AssemblePairs.sequential",  "HD09N-C_assemble-pass.fastq"),
        ("10 MaskPrimers.align",         "HD09N-C_primers-pass.fastq"),
        ("11 ParseHeaders.collapse",     "HD09N-C_primers-pass_reheader.fastq"),
        ("12 CollapseSeq",               "HD09N-C_collapse-unique.fastq"),
        ("13 SplitSeq.group",            "HD09N-C_atleast-2.fastq"),
        ("14 ParseHeaders.table",        "HD09N-C_atleast-2_headers.tab"),
    ],
    "umi2x250": [
        ("1  FilterSeq.quality R1",      "MS12_R1_quality-pass.fastq"),
        ("2  FilterSeq.quality R2",      "MS12_R2_quality-pass.fastq"),
        ("3  MaskPrimers.score R1",      "MS12_R1_primers-pass.fastq"),
        ("4  MaskPrimers.score R2",      "MS12_R2_primers-pass.fastq"),
        ("5  PairSeq",                   "MS12_R1_primers-pass_pair-pass.fastq"),
        ("6  BuildConsensus R1",         "MS12_R1_consensus-pass.fastq"),
        ("7  BuildConsensus R2",         "MS12_R2_consensus-pass.fastq"),
        ("8  PairSeq",                   "MS12_R1_consensus-pass_pair-pass.fastq"),
        ("9  AssemblePairs.align",       "MS12_assemble-pass.fastq"),
        ("10 ParseHeaders.collapse",     "MS12_assemble-pass_reheader.fastq"),
        ("11 CollapseSeq",               "MS12_collapse-unique.fastq"),
        ("12 SplitSeq.group",            "MS12_atleast-2.fastq"),
        ("13 ParseHeaders.table",        "MS12_atleast-2_headers.tab"),
    ],
    "nonumi2x250": [
        ("1  AssemblePairs.align",       "M1_assemble-pass.fastq"),
        ("2  FilterSeq.quality",         "M1_quality-pass.fastq"),
        ("3  MaskPrimers.score V",       "M1-FWD_primers-pass.fastq"),
        ("4  MaskPrimers.score C",       "M1-REV_primers-pass.fastq"),
        ("5  CollapseSeq",               "M1_collapse-unique.fastq"),
        ("6  SplitSeq.group",            "M1_atleast-2.fastq"),
        ("7  ParseHeaders.table",        "M1_atleast-2_headers.tab"),
    ],
}


def count(path: Path) -> int | None:
    if not path.is_file():
        return None
    n = sum(1 for _ in open(path, "rb"))
    return max(0, n - 1) if path.suffix == ".tab" else n // 4


def airrprep_counts(stats):
    """remaining-per-step, flattened to one number per step index."""
    out = {}
    for e in stats or []:
        idx = e.get("index")
        out[idx] = {
            "before": e.get("before"),
            "remaining": e.get("remaining"),
            "by_lane": e.get("by_lane"),
        }
    return out


def main():
    results = json.loads((BENCH / "results.json").read_text())
    for name, slot in results.items():
        print("=" * 78)
        print(name, "--", slot["label"])
        print("  CLI-pRESTO runs :", slot["cli"])
        print("  AIRRPrep   runs :", slot["airrprep"])
        ap = airrprep_counts((slot.get("last_job") or {}).get("step_stats"))
        rep_dirs = sorted((BENCH / "cli" / name).glob("run"))
        d = rep_dirs[-1] if rep_dirs else None
        print()
        print("  %-28s %>12s %12s" .replace(">", "") % ("step", "CLI", "AIRRPrep"))
        for i, (label, fname) in enumerate(CLI_STEPS[name], start=1):
            c = count(d / fname) if d else None
            entry = ap.get(i, {})
            a = entry.get("remaining")
            # PairSeq keeps both mates, so its `remaining` is the total over
            # lanes while the CLI file counted here holds one mate. Compare
            # against the matching lane so the two sides are the same quantity.
            lanes = entry.get("by_lane") or {}
            lane = next((L for L in ("R1", "R2") if L in fname), None)
            if lane in lanes:
                a = lanes[lane].get("remaining")
            flag = "" if (c is None or a is None or c == a) else "   <-- MISMATCH"
            print("  %-28s %12s %12s%s" % (label,
                                           "-" if c is None else f"{c:,}",
                                           "-" if a is None else f"{a:,}",
                                           flag))
        print()


if __name__ == "__main__":
    main()
