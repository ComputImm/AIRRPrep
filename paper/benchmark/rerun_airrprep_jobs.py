# -*- coding: utf-8 -*-
"""
Re-run the AIRRPrep side of the three benchmark workflows, without touching the
recorded timings.

compare_records.py compares the CLI outputs in cli/*/run against the AIRRPrep
job named by results.json["<workflow>"]["last_job"]. After a change to pipeline
code that run is stale, but a full benchmark.py round would also re-time both
sides -- and a timing measured next to other work on this machine is not
comparable with the published ones (see the harness notes). So this script
dispatches the same payloads, replaces only "last_job", and leaves the
"airrprep" and "cli" arrays alone.

    cd presto-backend/temp/bench
    python rerun_airrprep_jobs.py              # all three
    python rerun_airrprep_jobs.py race325275   # one

Needs the same stack as benchmark.py (Redis, uvicorn with the long-run email
gate raised, and a Celery worker started *after* the code change).
"""

import json
import sys

import benchmark as b


def main():
    only = sys.argv[1:] or list(b.WORKFLOWS)
    out = b.BENCH / "results.json"
    results = json.loads(out.read_text())

    for name in only:
        seconds, sid, jid, stats = b.run_airrprep(name, b.WORKFLOWS[name])
        slot = results[name]
        b._discard_workspace(slot.get("last_job"))
        slot["last_job"] = {"session": sid, "job": jid, "step_stats": stats}
        out.write_text(json.dumps(results, indent=2))
        print(f"{name:12s} job {jid} in {seconds:.1f}s (not recorded as a timing)",
              flush=True)


if __name__ == "__main__":
    main()
