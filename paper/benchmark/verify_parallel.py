# -*- coding: utf-8 -*-
"""
Does the assembly pool change the answer?

Runs AssembleSeq.sequential (the blastn path) over the same input twice -- once
with a single worker, once with the configured pool -- and compares the outputs
record for record. Same question, two execution strategies; the answer must be
identical.
"""

import hashlib
import shutil
import sys
import time
from pathlib import Path

from Bio import SeqIO

import app.presto_wrappers.assemble_pair as ap

BENCH = Path(__file__).resolve().parent
CLI = BENCH / "cli" / "race325275" / "rep1"
INPUTS = BENCH / "inputs"
WORK = BENCH / "verify"

N_PAIRS = int(sys.argv[1]) if len(sys.argv) > 1 else 1500


def head_n(src: Path, dst: Path, n: int):
    recs = []
    for i, r in enumerate(SeqIO.parse(str(src), "fastq")):
        if i >= n:
            break
        recs.append(r)
    SeqIO.write(recs, str(dst), "fastq")
    return len(recs)


def digest(path: Path):
    h = hashlib.sha256()
    ids = []
    for r in SeqIO.parse(str(path), "fastq"):
        ids.append(r.id)
        h.update(r.id.encode())
        h.update(str(r.seq).encode())
    return len(ids), h.hexdigest()


def run(workers: int, tag: str):
    out = WORK / f"{tag}.fastq"
    ap.EXTERNAL_TOOL_CPUS = workers
    t0 = time.perf_counter()
    res = ap.run_assemble_sequential(
        head_file=str(WORK / "head.fastq"),
        tail_file=str(WORK / "tail.fastq"),
        output_file=str(out),
        ref_file="REF",
        file_type="fastq",
        rc="tail",
        head_fields=["CONSCOUNT"],
        tail_fields=["CONSCOUNT", "PRCONS"],
        scan_reverse=True,
        aligner="blastn",
    )
    elapsed = time.perf_counter() - t0
    n, h = digest(Path(res["pass"]))
    print(f"  workers={workers:<2} {elapsed:8.2f}s  pass={res['pass_count']:>5} "
          f"fail={res['fail_count']:>5}  records={n:>5}  sha={h[:16]}")
    return elapsed, res["pass_count"], res["fail_count"], h


def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    # The script feeds -1 R2 -2 R1, so head is the R2 lane.
    n1 = head_n(CLI / "HD09N-R2_consensus-pass_pair-pass.fastq", WORK / "head.fastq", N_PAIRS)
    n2 = head_n(CLI / "HD09N-R1_consensus-pass_pair-pass.fastq", WORK / "tail.fastq", N_PAIRS)
    print(f"input: {n1} head / {n2} tail pairs\n")

    # The reference is read straight from disk here; the file store only exists
    # to turn an upload id into this path.
    ap._resolve_ref_path = lambda _f: str(INPUTS / "IMGT_Human_IG_V.fasta")

    serial = run(1, "serial")
    parallel = run(8, "parallel")

    print()
    same = serial[1:] == parallel[1:]
    print("identical output:", "YES" if same else "NO  <-- REGRESSION")
    if serial[0] and parallel[0]:
        print(f"speedup: {serial[0] / parallel[0]:.2f}x")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
