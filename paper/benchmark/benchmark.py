# -*- coding: utf-8 -*-
"""
Wall-clock comparison of the three predefined bulk workflows:
AIRRPrep (job dispatch -> job DONE, via the real HTTP API + Celery worker)
versus CLI-pRESTO (the reference shell script, one OS process per operation).

Both sides use the same interpreter (the backend venv, Python 3.11.8), the same
pRESTO 0.7.9 installation, the same 25,000-read-pair inputs and the same
filesystem. Upload and download are excluded from the AIRRPrep timing.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import redis
import requests

API = "http://127.0.0.1:8000"
# Job status is polled straight from Redis rather than through the HTTP status
# endpoint: the API is rate limited to 120 requests/minute, which would cap
# polling at ~2 s and blur the measurement. Redis holds the same document the
# status endpoint returns, so this reads exactly what the worker last wrote.
RDB = redis.from_url("redis://localhost:6379/0", decode_responses=True)
BENCH = Path(__file__).resolve().parent
INPUTS = BENCH / "inputs"
VENVPY = BENCH.parent.parent / "venv" / "Scripts" / "python.exe"
SCRIPTS = BENCH.parent.parent / "venv" / "Scripts"
JOBS = BENCH.parent.parent / "jobs"
UPLOADS = BENCH.parent.parent / "uploads"

REPS = int(os.getenv("BENCH_REPS", "3"))
POLL = 0.1


# --------------------------------------------------------------------------
# Pipeline payloads -- transcribed from the frontend's predefined definitions
# (src/pipelines/*.ts), with file ids substituted at run time.
# --------------------------------------------------------------------------

def race_steps(f):
    return [
        {"id": "step1_r1_quality", "name": "FilterSeq.quality", "lanes": "R1",
         "params": {"min_qual": 20}},
        {"id": "step2_r2_quality", "name": "FilterSeq.quality", "lanes": "R2",
         "params": {"min_qual": 20}},
        {"id": "step3_r1_primers", "name": "MaskPrimers.score", "lanes": "R1",
         "params": {"primer_file": f["primerR1"], "start": 0, "mode": "cut"}},
        {"id": "step4_r2_primers", "name": "MaskPrimers.score", "lanes": "R2",
         "params": {"primer_file": f["primerR2"], "start": 17, "barcode": True,
                    "mode": "cut", "max_error": 0.5}},
        {"id": "step5_pair", "name": "PairSeq.default", "lanes": "paired",
         "params": {"fields_2": ["BARCODE"], "coord_type": "sra"}},
        {"id": "step6_build_consensus_r1", "name": "BuildConsensus.default", "lanes": "R1",
         "params": {"barcode_field": "BARCODE", "primer_field": "PRIMER",
                    "primer_freq": 0.6, "max_error": 0.1, "max_gap": 0.5}},
        {"id": "step7_build_consensus_r2", "name": "BuildConsensus.default", "lanes": "R2",
         "params": {"barcode_field": "BARCODE", "max_error": 0.1, "max_gap": 0.5}},
        {"id": "step8_pair_consensus", "name": "PairSeq.default", "lanes": "paired",
         "params": {"coord_type": "presto"}},
        {"id": "step9_assemble", "name": "AssembleSeq.sequential", "lanes": "paired",
         "params": {"ref_file": f["reference"], "rc": "tail", "scan_reverse": True,
                    "swap_head_tail": True, "head_fields": ["CONSCOUNT"],
                    "tail_fields": ["CONSCOUNT", "PRCONS"], "aligner": "blastn"}},
        {"id": "step10_c_region", "name": "MaskPrimers.align", "lanes": "paired",
         "params": {"primer_file": f["cRegion"], "max_len": 100, "max_error": 0.3,
                    "mode": "tag", "rev_primer": True, "skip_rc": True,
                    "primer_field": "CREGION"}},
        {"id": "step11_collapse_headers", "name": "ParseHeaders.collapse", "lanes": "paired",
         "params": {"fields": ["CONSCOUNT"], "actions": ["min"]}},
        {"id": "step12_collapse_seq", "name": "CollapseSeq.default", "lanes": "paired",
         "params": {"max_missing": 20, "inner": True, "uniq_fields": ["CREGION"],
                    "copy_fields": ["CONSCOUNT"], "copy_actions": ["sum"]}},
        {"id": "step13_group_consensus", "name": "SplitSeq.group", "lanes": "paired",
         "params": {"field": "CONSCOUNT", "threshold": 2}},
        {"id": "step14_export_table", "name": "ParseHeaders.table", "lanes": "paired",
         "params": {"fields": ["ID", "CREGION", "CONSCOUNT", "DUPCOUNT"]}},
    ]


def umi_steps(f):
    return [
        {"id": "step1_r1_quality", "name": "FilterSeq.quality", "lanes": "R1",
         "params": {"min_qual": 20, "missing_chars": "#"}},
        {"id": "step2_r2_quality", "name": "FilterSeq.quality", "lanes": "R2",
         "params": {"min_qual": 20, "missing_chars": "#"}},
        {"id": "step3_r1_primers", "name": "MaskPrimers.score", "lanes": "R1",
         "params": {"primer_file": f["cprimer"], "start": 15, "mode": "cut",
                    "barcode": True}},
        {"id": "step4_r2_primers", "name": "MaskPrimers.score", "lanes": "R2",
         "params": {"primer_file": f["vprimer"], "start": 0, "mode": "mask"}},
        {"id": "step5_pair", "name": "PairSeq.default", "lanes": "paired",
         "params": {"fields_1": ["BARCODE"], "coord_type": "sra"}},
        {"id": "step6_build_consensus_r1", "name": "BuildConsensus.default", "lanes": "R1",
         "params": {"barcode_field": "BARCODE", "primer_field": "PRIMER",
                    "primer_freq": 0.6, "max_error": 0.1, "max_gap": 0.5}},
        {"id": "step7_build_consensus_r2", "name": "BuildConsensus.default", "lanes": "R2",
         "params": {"barcode_field": "BARCODE", "max_error": 0.1, "max_gap": 0.5}},
        {"id": "step8_pair_consensus", "name": "PairSeq.default", "lanes": "paired",
         "params": {"coord_type": "presto"}},
        {"id": "step9_assemble", "name": "AssembleSeq.align", "lanes": "paired",
         "params": {"swap_head_tail": True, "rc": "tail",
                    "head_fields": ["CONSCOUNT"], "tail_fields": ["CONSCOUNT", "PRCONS"]}},
        {"id": "step10_collapse_headers", "name": "ParseHeaders.collapse", "lanes": "paired",
         "params": {"fields": ["CONSCOUNT"], "actions": ["min"]}},
        {"id": "step11_collapse_seq", "name": "CollapseSeq.default", "lanes": "paired",
         "params": {"max_missing": 20, "inner": True, "uniq_fields": ["PRCONS"],
                    "copy_fields": ["CONSCOUNT"], "copy_actions": ["sum"]}},
        {"id": "step12_group_consensus", "name": "SplitSeq.group", "lanes": "paired",
         "params": {"field": "CONSCOUNT", "threshold": 2}},
        {"id": "step13_export_table", "name": "ParseHeaders.table", "lanes": "paired",
         "params": {"fields": ["ID", "PRCONS", "CONSCOUNT", "DUPCOUNT"]}},
    ]


def nonumi_steps(f):
    return [
        {"id": "step1_assemble", "name": "AssembleSeq.align", "lanes": "paired",
         "params": {"swap_head_tail": True, "rc": "tail"}},
        {"id": "step2_quality", "name": "FilterSeq.quality", "lanes": "paired",
         "params": {"min_qual": 20}},
        {"id": "step3_v_primers", "name": "MaskPrimers.score", "lanes": "paired",
         "params": {"primer_file": f["vprimer"], "start": 4, "mode": "mask",
                    "primer_field": "VPRIMER"}},
        {"id": "step4_c_primers", "name": "MaskPrimers.score", "lanes": "paired",
         "params": {"primer_file": f["cprimer"], "start": 4, "mode": "cut",
                    "rev_primer": True, "primer_field": "CPRIMER"}},
        {"id": "step5_collapse_seq", "name": "CollapseSeq.default", "lanes": "paired",
         "params": {"max_missing": 20, "inner": True, "uniq_fields": ["CPRIMER"],
                    "copy_fields": ["VPRIMER"], "copy_actions": ["set"]}},
        {"id": "step6_group", "name": "SplitSeq.group", "lanes": "paired",
         "params": {"field": "DUPCOUNT", "threshold": 2}},
        {"id": "step7_export_table", "name": "ParseHeaders.table", "lanes": "paired",
         "params": {"fields": ["ID", "DUPCOUNT", "CPRIMER", "VPRIMER"]}},
    ]


WORKFLOWS = {
    "race325275": {
        "label": "UMI-barcoded 5'RACE MiSeq 325+275 (SRR4026043)",
        "reads": ["SRR4026043_1.fastq", "SRR4026043_2.fastq"],
        "aux": {"primerR1": "AbSeq_R1_Human_IG_Primers.fasta",
                "primerR2": "AbSeq_R2_TS.fasta",
                "reference": "IMGT_Human_IG_V.fasta",
                "cRegion": "AbSeq_Human_IG_InternalCRegion.fasta"},
        "steps": race_steps,
        "cli": "cli_race.sh",
        "cli_files": ["SRR4026043_1.fastq", "SRR4026043_2.fastq",
                      "AbSeq_R1_Human_IG_Primers.fasta", "AbSeq_R2_TS.fasta",
                      "IMGT_Human_IG_V.fasta", "AbSeq_Human_IG_InternalCRegion.fasta"],
    },
    "umi2x250": {
        "label": "UMI-barcoded 5'RACE MiSeq 2x250 (SRR1383456)",
        "reads": ["SRR1383456_1.fastq", "SRR1383456_2.fastq"],
        "aux": {"cprimer": "Stern2014_CPrimers.fasta",
                "vprimer": "Stern2014_VPrimers.fasta"},
        "steps": umi_steps,
        "cli": "cli_umi.sh",
        "cli_files": ["SRR1383456_1.fastq", "SRR1383456_2.fastq",
                      "Stern2014_CPrimers.fasta", "Stern2014_VPrimers.fasta"],
    },
    "nonumi2x250": {
        "label": "MiSeq 2x250 BCR mRNA (ERR346600)",
        "reads": ["ERR346600_1.fastq", "ERR346600_2.fastq"],
        "aux": {"vprimer": "Greiff2014_VPrimers.fasta",
                "cprimer": "Greiff2014_CPrimers.fasta"},
        "steps": nonumi_steps,
        "cli": "cli_nonumi.sh",
        "cli_files": ["ERR346600_1.fastq", "ERR346600_2.fastq",
                      "Greiff2014_VPrimers.fasta", "Greiff2014_CPrimers.fasta"],
    },
}


# --------------------------------------------------------------------------


def new_session():
    r = requests.post(f"{API}/api/sessions", timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["session_id"], d["session_token"]


def upload(sid, token, path: Path):
    with open(path, "rb") as fh:
        r = requests.post(
            f"{API}/api/sessions/{sid}/files",
            headers={"X-Session-Token": token},
            files={"file": (path.name, fh, "application/octet-stream")},
            timeout=600,
        )
    r.raise_for_status()
    return r.json()["file_id"]


def run_airrprep(name, wf):
    """One AIRRPrep run: fresh session, upload, then time dispatch -> DONE."""
    sid, token = new_session()
    ids = {}
    for key, fname in wf["aux"].items():
        ids[key] = upload(sid, token, INPUTS / fname)
    read_ids = [upload(sid, token, INPUTS / f) for f in wf["reads"]]

    payload = {
        "session_id": sid,
        "file_ids": read_ids,
        "convert_to_fasta": False,
        "steps": wf["steps"](ids),
        "route": "/bulk",
        "label": f"benchmark {name}",
    }

    t0 = time.perf_counter()
    r = requests.post(
        f"{API}/jobs/start",
        headers={"X-Session-Token": token, "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=300,
    )
    if r.status_code != 200:
        raise RuntimeError(f"start failed {r.status_code}: {r.text[:800]}")
    job_id = r.json()["job_id"]

    key = f"session:{sid}:job:{job_id}"
    status = None
    job = {}
    while True:
        raw = RDB.get(key)
        job = json.loads(raw) if raw else {}
        status = str(job.get("status") or "")
        if status == "DONE" or status.startswith("FAILED") or status.startswith("Fail"):
            break
        time.sleep(POLL)
    elapsed = time.perf_counter() - t0

    if status != "DONE":
        raise RuntimeError(f"job {job_id} ended {status}: {job.get('error')}")

    stats = job.get("step_stats", [])
    return elapsed, sid, job_id, stats


CLI_TIMEOUT = int(os.getenv("CLI_TIMEOUT", "1800"))


def _run_cli_once(name, wf, rep, attempt):
    # One directory per workflow rather than per repetition: a full round of
    # intermediates is ~1 GB, and only the last round is needed afterwards to
    # count records. Repetitions overwrite each other.
    d = BENCH / "cli" / name / "run"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for f in wf["cli_files"]:
        shutil.copy2(INPUTS / f, d / f)
    t0 = time.perf_counter()
    p = subprocess.run(
        ["bash", str(BENCH / wf["cli"]), str(VENVPY), str(SCRIPTS)],
        cwd=str(d), env=dict(os.environ), capture_output=True, text=True,
        timeout=CLI_TIMEOUT,
    )
    elapsed = time.perf_counter() - t0
    (d / "cli.log").write_text(p.stdout + "\n" + p.stderr,
                               encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(
            f"CLI {name} rep{rep} failed rc={p.returncode}\n{p.stderr[-2000:]}"
        )
    return elapsed


def run_cli(name, wf, rep, attempts=3):
    """
    Time one CLI-pRESTO run, retrying a run that hangs.

    pRESTO's command line fans each operation out over --nproc worker processes,
    and on Windows that occasionally deadlocks: the workers stay alive with a
    few seconds of CPU each and the step never finishes. It is intermittent --
    the same workflow completed normally on other repetitions -- so a hung
    attempt is killed and retried rather than being allowed to stall the whole
    benchmark or, worse, be recorded as a legitimate time.
    """
    for attempt in range(1, attempts + 1):
        try:
            return _run_cli_once(name, wf, rep, attempt)
        except subprocess.TimeoutExpired:
            print(f"       ! CLI {name} rep{rep} hung >{CLI_TIMEOUT}s "
                  f"(attempt {attempt}/{attempts}); killing and retrying",
                  flush=True)
            _kill_stray_cli()
    raise RuntimeError(f"CLI {name} rep{rep} hung on every attempt")


def _kill_stray_cli():
    """Reap pRESTO worker processes left behind by a killed run."""
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
         "Where-Object { $_.CommandLine -like '*multiprocessing.spawn*' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
         "-ErrorAction SilentlyContinue }"],
        capture_output=True,
    )
    time.sleep(2)


def _discard_workspace(last_job):
    """Delete a previously measured run's job workspace and its uploads."""
    if not last_job:
        return
    sid, jid = last_job.get("session"), last_job.get("job")
    if not sid or not jid:
        return
    shutil.rmtree(JOBS / sid / jid, ignore_errors=True)
    shutil.rmtree(UPLOADS / sid, ignore_errors=True)


def main():
    only = sys.argv[1:] or list(WORKFLOWS)
    out = BENCH / "results.json"
    results = json.loads(out.read_text()) if out.exists() else {}

    for rep in range(1, REPS + 1):
        for name in only:
            wf = WORKFLOWS[name]
            slot = results.setdefault(name, {"label": wf["label"],
                                             "airrprep": [], "cli": []})

            t = run_cli(name, wf, rep)
            slot["cli"].append(round(t, 2))
            print(f"[rep{rep}] {name:12s} CLI-pRESTO {t:8.2f}s", flush=True)
            out.write_text(json.dumps(results, indent=2))

            t, sid, jid, stats = run_airrprep(name, wf)
            slot["airrprep"].append(round(t, 2))
            # The step counts are what matters afterwards and they are stored
            # here; the workspace itself is ~100-200 MB per run, so the previous
            # one goes as soon as this one has been recorded.
            _discard_workspace(slot.get("last_job"))
            slot["last_job"] = {"session": sid, "job": jid, "step_stats": stats}
            print(f"[rep{rep}] {name:12s} AIRRPrep   {t:8.2f}s", flush=True)
            out.write_text(json.dumps(results, indent=2))

    print("\n=== summary (median of %d) ===" % REPS)
    for name, slot in results.items():
        med = lambda xs: sorted(xs)[len(xs) // 2] if xs else float("nan")
        a, c = med(slot["airrprep"]), med(slot["cli"])
        print(f"{name:12s} AIRRPrep {a:8.2f}s  CLI {c:8.2f}s  ratio {c/a:5.2f}x")


if __name__ == "__main__":
    main()
