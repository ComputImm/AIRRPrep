# -*- coding: utf-8 -*-
"""
Correctness and payoff for the align and join pools.

align does real per-pair work (overlap scoring); join concatenates. Both are
run serially and pooled over the same input, and the outputs are compared, so
the width for each mode is chosen from a measurement rather than a guess.
"""

import hashlib
import shutil
import sys
import time
from pathlib import Path

from Bio import SeqIO

import app.presto_wrappers.assemble_pair as ap

BENCH = Path(__file__).resolve().parent
INPUTS = BENCH / "inputs"
WORK = BENCH / "verify_aj"

N_PAIRS = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


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
    n = 0
    for r in SeqIO.parse(str(path), "fastq"):
        n += 1
        h.update(r.id.encode())
        h.update(str(r.seq).encode())
    return n, h.hexdigest()


def run(mode, workers, tag):
    out = WORK / f"{tag}.fastq"
    ap.EXTERNAL_TOOL_CPUS = workers
    ap.JOIN_CPUS = workers
    fn = ap.run_assemble_align if mode == "align" else ap.run_assemble_join
    kw = dict(
        head_file=str(WORK / "head.fastq"),
        tail_file=str(WORK / "tail.fastq"),
        output_file=str(out),
        file_type="fastq",
        rc="tail",
    )
    t0 = time.perf_counter()
    res = fn(**kw)
    elapsed = time.perf_counter() - t0
    n, h = digest(Path(res["pass"]))
    print(f"  {mode:<6} workers={workers:<2} {elapsed:8.2f}s  pass={res['pass_count']:>6} "
          f"fail={res['fail_count']:>6}  sha={h[:16]}")
    return elapsed, res["pass_count"], res["fail_count"], h


def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    n1 = head_n(INPUTS / "ERR346600_2.fastq", WORK / "head.fastq", N_PAIRS)
    n2 = head_n(INPUTS / "ERR346600_1.fastq", WORK / "tail.fastq", N_PAIRS)
    print(f"input: {n1}/{n2} pairs\n")

    ok = True
    for mode in ("align", "join"):
        serial = run(mode, 1, f"{mode}_serial")
        pooled = run(mode, 8, f"{mode}_pool")
        same = serial[1:] == pooled[1:]
        ok = ok and same
        print(f"  -> identical: {'YES' if same else 'NO  <-- REGRESSION'}   "
              f"speedup: {serial[0] / pooled[0]:.2f}x\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
