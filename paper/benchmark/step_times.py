# -*- coding: utf-8 -*-
"""
Per-step wall time for both sides, reconstructed from output-file mtimes.

CLI-pRESTO writes one output file per operation into its run directory;
AIRRPrep writes each step's output into jobs/<session>/<job>/steps/NN/. In both
cases the mtime of a step's output is when that step finished, so consecutive
differences give the per-step duration.
"""

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parent
JOBS = BENCH.parent.parent / "jobs"

from compare_outputs import CLI_STEPS, count


def cli_step_times(name):
    rep = sorted((BENCH / "cli" / name).glob("run"))
    if not rep:
        return []
    d = rep[-1]
    # The run started when the copied inputs were last touched; the first
    # pRESTO output is the first thing the run itself writes.
    inputs = [p for p in d.iterdir() if p.suffix in (".fastq", ".fasta")
              and not any(p.name == f for _, f in CLI_STEPS[name])]
    start = max((p.stat().st_mtime for p in inputs), default=None)
    rows, prev = [], start
    for label, fname in CLI_STEPS[name]:
        p = d / fname
        if not p.is_file():
            rows.append((label, None, None))
            continue
        end = p.stat().st_mtime
        rows.append((label, (end - prev) if prev else None, count(p)))
        prev = end
    return rows


def airrprep_step_times(name, session, job):
    base = JOBS / session / job / "steps"
    if not base.is_dir():
        return []
    rows, prev = [], None
    for d in sorted(base.iterdir()):
        files = [p for p in d.iterdir() if p.is_file() and "_fail" not in p.name]
        if not files:
            continue
        end = max(p.stat().st_mtime for p in files)
        start = min(p.stat().st_ctime for p in files)
        prev = prev or start
        rows.append((d.name, end - prev, count(files[0])))
        prev = end
    return rows


def main():
    results = json.loads((BENCH / "results.json").read_text())
    for name, slot in results.items():
        print("=" * 72)
        print(name, "-", slot["label"])
        lj = slot.get("last_job") or {}
        cli = cli_step_times(name)
        ap = airrprep_step_times(name, lj.get("session", ""), lj.get("job", ""))
        print("  %-28s %10s %10s   %10s %10s" %
              ("step", "CLI s", "CLI n", "AIRRPrep s", "AIRRPrep n"))
        for i in range(max(len(cli), len(ap))):
            lab, ct, cn = cli[i] if i < len(cli) else ("?", None, None)
            _, at, an = ap[i] if i < len(ap) else (None, None, None)
            f = lambda v, d=1: "-" if v is None else (f"{v:,.{d}f}" if d else f"{v:,}")
            print("  %-28s %10s %10s   %10s %10s" %
                  (lab, f(ct), f(cn, 0), f(at), f(an, 0)))
        print("  totals: CLI %s   AIRRPrep %s" % (slot["cli"], slot["airrprep"]))
        print()


if __name__ == "__main__":
    main()
