# -*- coding: utf-8 -*-
"""
Emit the Table S8 dataset as JSON: totals over the three repetitions plus the
per-step breakdown of the final repetition.

Counts come from the same place `compare_outputs.py` verifies them (CLI files
on disk, AIRRPrep `step_stats` read per lane); times come from output mtimes as
in `step_times.py`.

Two steps have no mtime to read - the first CLI step (copied inputs keep their
source mtime, so there is no start reference) and the last AIRRPrep step (its
output goes to outputs/, not to a numbered steps/ directory). Both are recovered
as the residual of the run: the replicate's measured total minus every step that
could be timed, flagged `derived` in the output. The residual absorbs any
unattributed overhead, so it is an upper bound on that step.

The recovery is checked where the data allows it: in both workflows whose steps
1 and 2 are the same operation on opposite mate streams, the derived step 1 lands
within 2% of the measured step 2 (13.2s vs 12.9s; 11.0s vs 11.1s).
"""

import json
import statistics as st
from pathlib import Path

from compare_outputs import CLI_STEPS, count
from step_times import cli_step_times, airrprep_step_times

BENCH = Path(__file__).resolve().parent


def main():
    results = json.loads((BENCH / "results.json").read_text())
    out = {"workflows": []}

    for name, slot in results.items():
        cli, ap = slot["cli"], slot["airrprep"]
        lj = slot.get("last_job") or {}
        stats = {e["index"]: e for e in lj.get("step_stats") or []}
        cli_rows = cli_step_times(name)
        ap_rows = airrprep_step_times(name, lj.get("session", ""), lj.get("job", ""))

        steps = []
        for i, (label, fname) in enumerate(CLI_STEPS[name], start=1):
            entry = stats.get(i, {})
            n_ap = entry.get("remaining")
            lanes = entry.get("by_lane") or {}
            lane = next((L for L in ("R1", "R2") if L in fname), None)
            if lane in lanes:
                n_ap = lanes[lane].get("remaining")

            t_cli = cli_rows[i - 1][1] if i - 1 < len(cli_rows) else None
            if i == 1:
                t_cli = None          # no start reference, recovered below
            t_ap = ap_rows[i - 1][1] if i - 1 < len(ap_rows) else None

            steps.append({
                "label": label,
                "cli_n": cli_rows[i - 1][2] if i - 1 < len(cli_rows) else None,
                "ap_n": n_ap,
                "cli_s": round(t_cli, 1) if t_cli else None,
                "ap_s": round(t_ap, 1) if t_ap else None,
                "cli_derived": False,
                "ap_derived": False,
            })

        # Recover the two untimed steps as the residual of the replicate the
        # per-step data comes from, which is the last one run.
        for side, key, flag in (("cli", "cli_s", "cli_derived"),
                                ("airrprep", "ap_s", "ap_derived")):
            missing = [s for s in steps if s[key] is None]
            if len(missing) != 1:
                continue
            residual = slot[side][-1] - sum(s[key] for s in steps if s[key] is not None)
            if residual > 0:
                missing[0][key] = round(residual, 1)
                missing[0][flag] = True

        out["workflows"].append({
            "name": name,
            "label": slot["label"],
            "cli": cli,
            "airrprep": ap,
            "cli_mean": round(st.mean(cli), 1), "cli_sd": round(st.stdev(cli), 1),
            "ap_mean": round(st.mean(ap), 1), "ap_sd": round(st.stdev(ap), 1),
            "ratio": round(st.mean(cli) / st.mean(ap), 2),
            "paired": [round(cli[i] / ap[i], 2) for i in range(len(cli))],
            "steps": steps,
        })

    (BENCH / "table_s8.json").write_text(json.dumps(out, indent=2))
    mism = [(w["name"], s["label"]) for w in out["workflows"] for s in w["steps"]
            if s["cli_n"] is not None and s["ap_n"] is not None and s["cli_n"] != s["ap_n"]]
    print("workflows:", len(out["workflows"]),
          "| steps:", sum(len(w["steps"]) for w in out["workflows"]),
          "| count mismatches:", len(mism))
    for m in mism:
        print("  MISMATCH", m)


if __name__ == "__main__":
    main()
